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
    emb = Embeddings(cfg.embedding_model)
    es = ElasticsearchStore(cfg.elastic_url, cfg.elastic_index)
    es.ensure_index()
    qd = QdrantStore(cfg.qdrant_url, cfg.qdrant_collection, emb.dim)
    qd.ensure_collection()
    neo = Neo4jStore(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)
    neo.ensure_schema()

    # Index documents to Elasticsearch
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
        vectors = emb.encode(all_texts, batch_size=64)
        qd.upsert(all_chunk_ids, vectors, all_payloads)
        print(f"Vetores inseridos no Qdrant: {len(all_texts)} chunks.")
    else:
        print("Nenhum chunk gerado.")

    neo.close()
    print("Ingestão concluída.")


if __name__ == "__main__":
    main()
