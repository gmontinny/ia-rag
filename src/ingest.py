import os
from typing import List, Dict
from tqdm import tqdm

from .config import load_settings
from .parsers import load_documents
from .chunker import hybrid_chunk
from .embeddings import Embeddings
from .stores.elasticsearch_store import ElasticsearchStore
from .stores.qdrant_store import QdrantStore
from .stores.neo4j_store import Neo4jStore


def main():
    cfg = load_settings()

    # Load source documents
    docs = load_documents(cfg.data_dir)
    if not docs:
        print(f"Nenhum documento encontrado em {cfg.data_dir}.")
        return

    # Initialize components
    print("[Ingest] Inicializando embeddings...")
    emb = Embeddings(
        cfg.embedding_model,
        hf_token=cfg.hf_token,
        local_files_only=cfg.hf_local_files_only,
        force_backend=cfg.emb_force_backend,
    )
    print("[Ingest] Inicializando ElasticsearchStore e garantindo índice...")
    es = ElasticsearchStore(cfg.elastic_url, cfg.elastic_index, timeout=cfg.es_timeout)
    es.ensure_index()
    print("[Ingest] Inicializando QdrantStore e garantindo coleção...")
    qd = QdrantStore(
        cfg.qdrant_url,
        cfg.qdrant_collection,
        emb.dim,
        upsert_batch=cfg.qdrant_upsert_batch,
        timeout=cfg.qdrant_timeout,
        retries=cfg.qdrant_retries,
    )
    qd.ensure_collection()
    print("[Ingest] Inicializando Neo4jStore e garantindo schema...")
    neo = Neo4jStore(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password, timeout=cfg.neo4j_timeout)
    neo.ensure_schema()

    # Index documents to Elasticsearch
    print("[Ingest] Indexando documentos no Elasticsearch...")
    for d in docs:
        es.index_document(
            d.doc_id,
            {
                "title": d.title,
                "content": d.content,
                "source_path": d.source_path,
                "meta": d.meta,
            },
        )

    # Chunk, embed, and store chunks
    print("[Ingest] Gerando chunks e populando Neo4j...")
    all_chunk_ids: List[str] = []
    all_texts: List[str] = []
    all_payloads: List[Dict] = []

    for d in tqdm(docs, desc="Gerando chunks"):
        chunks = hybrid_chunk(d)
        for c in chunks:
            parent_label, parent_id = neo.upsert_hierarchy(
                c.legal_ref.law_id,
                c.legal_ref.article,
                c.legal_ref.paragraph,
                c.legal_ref.inciso,
            )
            neo.attach_chunk(parent_id=parent_id, chunk_id=c.chunk_id, text=c.text, start_char=c.start_char, end_char=c.end_char)
            all_chunk_ids.append(c.chunk_id)
            all_texts.append(c.text)
            all_payloads.append(
                {
                    "doc_id": c.doc_id,
                    "law_id": c.legal_ref.law_id,
                    "article": c.legal_ref.article,
                    "paragraph": c.legal_ref.paragraph,
                    "inciso": c.legal_ref.inciso,
                    "start": c.start_char,
                    "end": c.end_char,
                }
            )

    if all_texts:
        print(f"[Ingest] Gerando embeddings para {len(all_texts)} chunks...")
        vectors = emb.encode(all_texts, batch_size=64)
        print("[Ingest] Upsert dos vetores no Qdrant (em lotes)...")
        qd.upsert(all_chunk_ids, vectors, all_payloads)
        print(f"[Ingest] Vetores inseridos no Qdrant: {len(all_texts)} chunks.")
    else:
        print("Nenhum chunk gerado.")

    print("[Ingest] Fechando conexão com Neo4j...")
    neo.close()
    print("[Ingest] Ingestão concluída.")


if __name__ == "__main__":
    main()
