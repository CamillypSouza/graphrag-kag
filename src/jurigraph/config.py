"""Configuração lida do .env (nunca versionado)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parâmetros do sistema; todos sobrescrevíveis por variável de ambiente."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("graphrag-kag-dev")
    neo4j_database: str = "neo4j"

    llm_provider: str = "openai"
    llm_model: str = "gpt-5.4-mini"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    ollama_host: str = "http://localhost:11434"
    llm_price_input_per_m: float = 0.0
    llm_price_output_per_m: float = 0.0

    embedding_provider: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimensions: int = 384

    er_fuzzy_threshold: float = 92.0
    er_embed_threshold: float = 0.92

    retrieval_top_k: int = 6
    cypher_max_limit: int = 50
    cypher_timeout_seconds: float = 15.0
    min_evidence_score: float = 0.35

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"

    @property
    def logs_dir(self) -> Path:
        return ROOT / "logs"


@lru_cache
def get_settings() -> Settings:
    """Instância única das configurações."""
    return Settings()
