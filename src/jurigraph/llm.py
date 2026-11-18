"""Fábrica de LLM e embeddings, com contagem de tokens para estimar custo."""

import logging
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from neo4j_graphrag.embeddings.base import Embedder
from neo4j_graphrag.llm import LLMInterface, LLMResponse, OpenAILLM
from pydantic import BaseModel, ConfigDict

from jurigraph.config import get_settings

log = logging.getLogger(__name__)


class Estrito(BaseModel):
    """Base dos modelos de saída estruturada (a OpenAI exige additionalProperties=false)."""

    model_config = ConfigDict(extra="forbid")


@dataclass
class Usage:
    """Tokens consumidos desde o último reset."""

    chamadas: int = 0
    entrada: int = 0
    saida: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, resp: LLMResponse) -> None:
        with self._lock:
            self.chamadas += 1
            if resp.usage:
                self.entrada += resp.usage.request_tokens or 0
                self.saida += resp.usage.response_tokens or 0

    def custo_usd(self) -> float:
        s = get_settings()
        return (self.entrada * s.llm_price_input_per_m + self.saida * s.llm_price_output_per_m) / 1e6

    def snapshot(self) -> dict[str, float]:
        return {"chamadas": self.chamadas, "tokens_entrada": self.entrada,
                "tokens_saida": self.saida, "custo_usd": round(self.custo_usd(), 4)}

    def reset(self) -> None:
        with self._lock:
            self.chamadas = self.entrada = self.saida = 0


USAGE = Usage()


class TrackedOpenAILLM(OpenAILLM):
    """OpenAILLM que soma o uso de tokens em USAGE."""

    def invoke(self, *args: Any, **kwargs: Any) -> LLMResponse:
        resp = super().invoke(*args, **kwargs)
        USAGE.add(resp)
        return resp

    async def ainvoke(self, *args: Any, **kwargs: Any) -> LLMResponse:
        resp = await super().ainvoke(*args, **kwargs)
        USAGE.add(resp)
        return resp


def make_llm(model: str | None = None) -> LLMInterface:
    """LLM do provedor configurado em LLM_PROVIDER."""
    s = get_settings()
    nome = model or s.llm_model
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY não definida no .env")
        return TrackedOpenAILLM(model_name=nome, api_key=s.openai_api_key.get_secret_value())
    if s.llm_provider == "anthropic":
        from neo4j_graphrag.llm import AnthropicLLM

        key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
        return AnthropicLLM(model_name=nome, api_key=key)
    if s.llm_provider == "ollama":
        from neo4j_graphrag.llm import OllamaLLM

        return OllamaLLM(model_name=nome, host=s.ollama_host)
    raise ValueError(f"LLM_PROVIDER desconhecido: {s.llm_provider}")


@lru_cache
def get_embedder() -> Embedder:
    """Embedder configurado, local por padrão. A dimensão precisa bater com o índice."""
    s = get_settings()
    if s.embedding_provider == "openai":
        from neo4j_graphrag.embeddings import OpenAIEmbeddings

        key = s.openai_api_key.get_secret_value() if s.openai_api_key else None
        return OpenAIEmbeddings(model=s.embedding_model, api_key=key)
    from neo4j_graphrag.embeddings import SentenceTransformerEmbeddings

    return SentenceTransformerEmbeddings(model=s.embedding_model)


def embed_batch(textos: list[str]) -> list[list[float]]:
    """Embeddings em lote no sentence-transformers e um a um nos outros provedores."""
    emb = get_embedder()
    modelo = getattr(emb, "model", None)
    if modelo is not None and hasattr(modelo, "encode"):
        vetores = modelo.encode(textos, batch_size=32, normalize_embeddings=True,
                                show_progress_bar=False)
        return [v.tolist() for v in vetores]
    return [emb.embed_query(t) for t in textos]
