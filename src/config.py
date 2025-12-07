import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    # Infra URLs
    elastic_url: str
    qdrant_url: str
    neo4j_url: str
    # Neo4j auth
    neo4j_user: str
    neo4j_password: str
    # Embeddings
    embedding_model: str
    hf_token: str
    hf_local_files_only: bool
    emb_force_backend: str
    # Timeouts
    es_timeout: float
    neo4j_timeout: float
    qdrant_timeout: float
    qdrant_retries: int
    # Data/indices
    data_dir: str
    qdrant_collection: str
    elastic_index: str
    qdrant_upsert_batch: int
    # LLM / RAG
    llm_provider: str
    gemini_api_key: str
    gemini_model: str
    openai_api_key: str
    openai_model: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        elastic_url=os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        neo4j_url=os.getenv("NEO4J_URL", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "ulysses-camara/legal-bert-pt-br"),
        hf_token=os.getenv("HUGGINGFACE_HUB_TOKEN", ""),
        hf_local_files_only=os.getenv("HF_LOCAL_FILES_ONLY", "false").lower() in ("1", "true", "yes"),
        emb_force_backend=os.getenv("EMB_FORCE_BACKEND", ""),
        es_timeout=float(os.getenv("ES_TIMEOUT", "15")),
        neo4j_timeout=float(os.getenv("NEO4J_TIMEOUT", "15")),
        qdrant_timeout=float(os.getenv("QDRANT_TIMEOUT", "60")),
        qdrant_retries=int(os.getenv("QDRANT_RETRIES", "3")),
        data_dir=os.getenv("DATA_DIR", "./data"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "anvisa_chunks"),
        elastic_index=os.getenv("ELASTIC_INDEX", "anvisa_docs"),
        qdrant_upsert_batch=int(os.getenv("QDRANT_UPSERT_BATCH", "256")),
        llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5"),
    )