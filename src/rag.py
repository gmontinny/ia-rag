from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from neo4j import GraphDatabase, Driver

from .config import load_settings
from .llm_providers import make_provider
from .search import bootstrap_clients as bootstrap_search_clients


@dataclass
class Evidence:
    chunk_id: str
    score: float
    law: Optional[str]
    article: Optional[str]
    paragraph: Optional[str]
    inciso: Optional[str]
    text: str


def _retrieve_evidence(query: str, topk: int = 6, use_hybrid: bool = True, filter_law: Optional[str] = None) -> List[Evidence]:
    """Busca evidências no Qdrant (opcionalmente filtradas por candidatos do ES e por law_id) e enriquece via Neo4j."""
    cfg = load_settings()
    cli = bootstrap_search_clients()  # es, qd, neo, model, indices
    es = cli.es
    qd: QdrantClient = cli.qd
    neo: Driver = cli.neo
    model: SentenceTransformer = cli.model

    # 1) Vetor da consulta
    qvec = model.encode([query], normalize_embeddings=True)[0].tolist()

    # 2) Construir filtro do Qdrant (ES candidatos + law_id opcional)
    must_conditions: List[qm.Condition] = []
    if use_hybrid:
        res = es.search(index=cli.es_index, query={"match": {"content": query}}, size=max(20, topk * 3), _source=False)
        candidate_doc_ids = [h["_id"] for h in res.get("hits", {}).get("hits", [])]
        if candidate_doc_ids:
            must_conditions.append(qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=candidate_doc_ids)))
    if filter_law:
        # Tenta correspondência por texto (substrings) em law_id
        try:
            must_conditions.append(qm.FieldCondition(key="law_id", match=qm.MatchText(text=str(filter_law))))
        except Exception:
            must_conditions.append(qm.FieldCondition(key="law_id", match=qm.MatchValue(value=str(filter_law))))
    qfilter = qm.Filter(must=must_conditions) if must_conditions else None

    # 3) Busca semântica
    hits = qd.search(collection_name=cli.qd_collection, query_vector=qvec, limit=topk, query_filter=qfilter)

    # 4) Enriquecer com texto/trilha no Neo4j
    cypher = (
        "MATCH (c:Chunk {id: $cid})\n"
        "OPTIONAL MATCH (l:Law)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (a:Article)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (p:Paragraph)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (i:Inciso)-[:HAS_CHUNK]->(c)\n"
        "RETURN c.text as text, l.id as law, a.id as article, p.id as paragraph, i.id as inciso"
    )
    evs: List[Evidence] = []
    with neo.session() as sess:
        for h in hits:
            payload = h.payload or {}
            cid = payload.get("chunk_id")
            if not cid:
                continue
            rec = sess.run(cypher, cid=cid).single()
            if not rec:
                continue
            evs.append(
                Evidence(
                    chunk_id=cid,
                    score=float(h.score or 0.0),
                    law=rec["law"],  # type: ignore[index]
                    article=rec["article"],  # type: ignore[index]
                    paragraph=rec["paragraph"],  # type: ignore[index]
                    inciso=rec["inciso"],  # type: ignore[index]
                    text=(rec["text"] or ""),  # type: ignore[index]
                )
            )
    try:
        cli.neo.close()
    except Exception:
        pass
    return evs


def _format_citation(ev: Evidence, idx: int) -> str:
    trail = []
    if ev.law:
        trail.append(f"Lei: {ev.law}")
    if ev.article:
        trail.append(f"Artigo: {ev.article}")
    if ev.paragraph:
        trail.append(f"Parágrafo: {ev.paragraph}")
    if ev.inciso:
        trail.append(f"Inciso: {ev.inciso}")
    meta = " | ".join(trail) if trail else ""
    return f"[{idx}] ({meta})\n{ev.text.strip()}"


def build_prompts(query: str, evidences: List[Evidence]) -> Dict[str, str]:
    system = (
        "Você é um analista jurídico especializado em legislação sanitária brasileira (ANVISA).\n"
        "Responda em português do Brasil, com precisão e neutralidade.\n"
        "Use EXCLUSIVAMENTE as evidências fornecidas; se não houver suporte, diga claramente que não encontrou base legal.\n"
        "Inclua uma seção 'Referências' citando os índices [n] das evidências utilizadas e a trilha (Lei→Art→§→Inciso) quando disponível.\n"
        "Quando relevante, extraia trechos exatos entre aspas e explique em linguagem simples.\n"
    )
    body_parts = [
        f"Pergunta do usuário:\n{query}\n",
        "\nEvidências (não invente além delas):\n",
    ]
    for i, ev in enumerate(evidences, start=1):
        body_parts.append(_format_citation(ev, i))
        body_parts.append("")
    body_parts.append(
        "\nInstruções de resposta:\n"
        "- Responda de forma direta e estruturada.\n"
        "- Liste as referências usadas como [n].\n"
        "- Se houver ambiguidades, aponte-as e sugira onde procurar na legislação.\n"
    )
    user = "\n".join(body_parts).strip()
    return {"system": system, "user": user}


def _build_fallback_answer(query: str, evidences: List[Evidence]) -> str:
    if not evidences:
        return (
            "Não encontrei evidências suficientes na base para responder à pergunta.\n"
            "Verifique se a ingestão foi executada (python main.py ingest) e tente reformular a consulta."
        )

    # Gera uma resposta extrativa estruturada com base nas evidências
    keywords = [
        "infração", "infrações", "penalidade", "penalidades", "sanção", "sanções",
        "multa", "advertência", "interdição", "suspensão", "cancelamento", "apreensão",
    ]
    def _sentences(txt: str) -> List[str]:
        import re
        # separa por ponto final, quebras de linha e ponto e vírgula
        raw = re.split(r"(?<=[\.!?])\s+|\n+|;\s+", (txt or "").strip())
        return [s.strip() for s in raw if s and len(s.strip()) > 3]

    extracted: List[str] = []
    used_refs: List[int] = []
    for idx, ev in enumerate(evidences[: min(5, len(evidences))], start=1):
        for s in _sentences(ev.text)[:20]:  # limita por evidência
            low = s.lower()
            if any(k in low for k in keywords):
                prefix = []
                if ev.article:
                    prefix.append(f"{ev.article}")
                if ev.paragraph:
                    prefix.append(f"{ev.paragraph}")
                if ev.inciso:
                    prefix.append(f"Inciso {ev.inciso}")
                ctx = (" – ".join(prefix) + ": ") if prefix else ""
                extracted.append(f"- {ctx}{s}")
                if idx not in used_refs:
                    used_refs.append(idx)
        if len(extracted) >= 12:
            break

    lines: List[str] = []
    lines.append("Não foi possível gerar uma resposta automática com o modelo neste momento.")
    if extracted:
        lines.append("Abaixo, um resumo extrativo de infrações/penalidades conforme os trechos recuperados:")
        lines.append("")
        lines.extend(extracted)
    else:
        lines.append("Segue um resumo dos trechos mais relevantes encontrados na base:")
        lines.append("")
        for i, ev in enumerate(evidences[: min(3, len(evidences))], start=1):
            trilha = []
            if ev.law:
                trilha.append(f"Lei: {ev.law}")
            if ev.article:
                trilha.append(f"Artigo: {ev.article}")
            if ev.paragraph:
                trilha.append(f"Parágrafo: {ev.paragraph}")
            if ev.inciso:
                trilha.append(f"Inciso: {ev.inciso}")
            trilha_str = " | ".join(trilha) if trilha else ""
            lines.append(f"[{i}] {trilha_str}")
            excerpt = (ev.text or "").strip().replace("\n", " ")
            lines.append(f"\"{excerpt[:500]}\"")
            lines.append("")
        used_refs = list(range(1, min(3, len(evidences)) + 1))
    if used_refs:
        lines.append("\nReferências: " + ", ".join(f"[{i}]" for i in used_refs))
    return "\n".join(lines)


def run_rag(
    query: str,
    topk: int = 6,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 800,
    use_hybrid: bool = True,
    filter_law: Optional[str] = None,
    debug_print: bool = False,
) -> str:
    cfg = load_settings()
    prov = (provider or cfg.llm_provider or "gemini").lower()
    if prov in ("gemini", "google", "googleai"):
        api_key = cfg.gemini_api_key
        model = model_name or cfg.gemini_model
    else:
        api_key = cfg.openai_api_key
        model = model_name or cfg.openai_model

    if not api_key:
        raise RuntimeError(
            "Chave de API ausente. Configure GEMINI_API_KEY ou OPENAI_API_KEY no .env conforme o provedor escolhido."
        )

    evidences = _retrieve_evidence(query, topk=topk, use_hybrid=use_hybrid, filter_law=filter_law)
    if debug_print:
        print(f"[RAG] Evidências recuperadas: {len(evidences)}")
        for i, ev in enumerate(evidences[:3], start=1):
            print(f"  - [{i}] chunk={ev.chunk_id} score={ev.score:.4f} law={ev.law} art={ev.article} par={ev.paragraph} inc={ev.inciso}")
    prompts = build_prompts(query, evidences)

    if debug_print:
        print("===== SYSTEM PROMPT =====\n" + prompts["system"])  # noqa: T201
        print("\n===== USER PROMPT =====\n" + prompts["user"])  # noqa: T201

    llm = make_provider(prov, model, api_key)
    try:
        answer = llm.generate(
            system_prompt=prompts["system"],
            user_prompt=prompts["user"],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        if debug_print:
            print(f"[RAG] Erro ao chamar o LLM: {e}")
        answer = ""

    if not evidences:
        return _build_fallback_answer(query, evidences)

    if not (answer or "").strip():
        # Fallback amistoso quando o provedor retorna string vazia
        return _build_fallback_answer(query, evidences)

    return answer
