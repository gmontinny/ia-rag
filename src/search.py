from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from elasticsearch import Elasticsearch
from neo4j import GraphDatabase, Driver
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from sentence_transformers import SentenceTransformer

from .config import load_settings


@dataclass
class Clients:
    es: Elasticsearch
    qd: QdrantClient
    neo: Driver
    model: SentenceTransformer
    es_index: str
    qd_collection: str


def bootstrap_clients() -> Clients:
    cfg = load_settings()
    es = Elasticsearch(cfg.elastic_url)
    qd = QdrantClient(url=cfg.qdrant_url)
    neo = GraphDatabase.driver(cfg.neo4j_url, auth=(cfg.neo4j_user, cfg.neo4j_password))
    model = SentenceTransformer(cfg.embedding_model)
    return Clients(
        es=es,
        qd=qd,
        neo=neo,
        model=model,
        es_index=cfg.elastic_index,
        qd_collection=cfg.qdrant_collection,
    )


def search_lexical_es(cli: Clients, query: str, size: int = 5):
    res = cli.es.search(
        index=cli.es_index,
        query={"match": {"content": query}},
        size=size,
        _source=["title", "source_path"],
    )
    hits = res.get("hits", {}).get("hits", [])
    print(f"[ES] {len(hits)} resultados para: '{query}'")
    for h in hits:
        _id = h.get("_id")
        _score = h.get("_score")
        src = h.get("_source", {})
        print(f"- id={_id} score={_score:.3f} title={src.get('title')} source={src.get('source_path')}")
    return hits


def search_semantic_qdrant(
    cli: Clients,
    query: str,
    limit: int = 5,
    filter_doc_ids: Optional[List[str]] = None,
):
    vec = cli.model.encode([query], normalize_embeddings=True)[0].tolist()
    qfilter = None
    if filter_doc_ids:
        qfilter = qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=filter_doc_ids))])

    results = cli.qd.search(
        collection_name=cli.qd_collection,
        query_vector=vec,
        limit=limit,
        query_filter=qfilter,
    )
    print(f"[Qdrant] {len(results)} resultados para: '{query}'")
    for r in results:
        p = r.payload or {}
        print(
            f"- score={r.score:.4f} law={p.get('law_id')} art={p.get('article')} par={p.get('paragraph')} inc={p.get('inciso')} chunk_id={p.get('chunk_id')}"
        )
    return results


def hybrid_search(cli: Clients, query: str, es_size: int = 10, qdrant_limit: int = 5):
    res = cli.es.search(index=cli.es_index, query={"match": {"content": query}}, size=es_size, _source=False)
    candidate_doc_ids = [h["_id"] for h in res.get("hits", {}).get("hits", [])]
    print("[Hybrid] Doc IDs candidatos (ES):", candidate_doc_ids or "(nenhum)")
    hits = search_semantic_qdrant(cli, query, limit=qdrant_limit, filter_doc_ids=candidate_doc_ids or None)
    return hits


def explain_chunk(cli: Clients, chunk_id: str, neighbors: bool = True):
    cypher = (
        "MATCH (c:Chunk {id: $cid})\n"
        "OPTIONAL MATCH (l:Law)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (a:Article)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (p:Paragraph)-[:HAS_CHUNK]->(c)\n"
        "OPTIONAL MATCH (i:Inciso)-[:HAS_CHUNK]->(c)\n"
        "RETURN c.id as chunk_id, c.text as text, l.id as law, a.id as article, p.id as paragraph, i.id as inciso"
    )
    with cli.neo.session() as sess:
        rec = sess.run(cypher, cid=chunk_id).single()
        if not rec:
            print(f"[Neo4j] Chunk não encontrado: {chunk_id}")
            return
        print("[Neo4j] Trilha legal do chunk:")
        print("- Lei:", rec["law"])  # type: ignore[index]
        print("- Artigo:", rec["article"])  # type: ignore[index]
        print("- Parágrafo:", rec["paragraph"])  # type: ignore[index]
        print("- Inciso:", rec["inciso"])  # type: ignore[index]
        txt = (rec["text"] or "").replace("\n", " ")  # type: ignore[index]
        print("- Trecho:", txt[:400], "...")

        if neighbors:
            cy_neighbors = (
                "MATCH (c:Chunk {id: $cid})<-[:HAS_CHUNK]-(a:Article)\n"
                "MATCH (a)-[:HAS_CHUNK]->(o:Chunk) WHERE o.id <> $cid\n"
                "RETURN o.id as chunk_id, o.text as text LIMIT 3"
            )
            rows = list(sess.run(cy_neighbors, cid=chunk_id))
            if rows:
                print("- Vizinhos (mesmo Artigo):")
                for row in rows:
                    print("  ·", row["chunk_id"], "→", (row["text"] or "").replace("\n", " ")[:200], "...")


def run_search(mode: str, query: str, size: int = 5, limit: int = 5, explain: bool = True):
    cli = bootstrap_clients()
    try:
        mode = (mode or "all").lower()
        best_hit = None

        if mode in ("lexical", "all"):
            print("\n=== Busca lexical (Elasticsearch) ===")
            search_lexical_es(cli, query, size=size)

        if mode in ("semantic", "all"):
            print("\n=== Busca semântica (Qdrant) ===")
            hits = search_semantic_qdrant(cli, query, limit=limit)
            best_hit = best_hit or (hits[0] if hits else None)

        if mode in ("hybrid", "all"):
            print("\n=== Busca híbrida (ES → Qdrant) ===")
            hits = hybrid_search(cli, query, es_size=size, qdrant_limit=limit)
            best_hit = best_hit or (hits[0] if hits else None)

        if explain and best_hit is not None:
            payload = best_hit.payload or {}
            cid = payload.get("chunk_id")
            if cid:
                print("\n=== Contexto no grafo (Neo4j) ===")
                explain_chunk(cli, cid, neighbors=True)
            else:
                print("\n[Info] Resultado sem chunk_id no payload para explicar no grafo.")
    finally:
        try:
            cli.neo.close()
        except Exception:
            pass
