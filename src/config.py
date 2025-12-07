import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    elastic_url: str
    qdrant_url: str
    neo4j_url: str
    neo4j_user: str
    neo4j_password: str
    embedding_model: str
    data_dir: str
    qdrant_collection: str
    elastic_index: str
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
        embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        data_dir=os.getenv("DATA_DIR", "./data"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "anvisa_chunks"),
        elastic_index=os.getenv("ELASTIC_INDEX", "anvisa_docs"),
        llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-pro-preview"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5"),
    )
