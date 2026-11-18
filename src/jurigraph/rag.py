"""Recupera, gera e verifica a resposta nos três modos da avaliação."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from jurigraph.generation.answer import RespostaLLM, gerar
from jurigraph.generation.verifier import Verificacao, verificar
from jurigraph.graph_algos.paths import resumos_relevantes
from jurigraph.llm import USAGE
from jurigraph.retrieval.context import Contexto
from jurigraph.retrieval.hybrid import busca_hibrida, busca_vetorial
from jurigraph.retrieval.kag_planner import resolver_kag
from jurigraph.retrieval.text2cypher import text2cypher

Modo = Literal["vetorial", "hibrido", "kag"]
MODOS: dict[str, str] = {
    "vetorial": "RAG vetorial puro (baseline)",
    "hibrido": "GraphRAG híbrido (vetor + fulltext + 2 saltos + Text-to-Cypher + comunidades)",
    "kag": "GraphRAG com planejador estilo KAG",
}


@dataclass
class Resposta:
    pergunta: str
    modo: str
    contexto: Contexto
    bruta: RespostaLLM
    verificacao: Verificacao
    segundos: float
    tokens: dict[str, float]

    @property
    def texto(self) -> str:
        return self.verificacao.resposta_final


def recuperar(pergunta: str, modo: Modo) -> Contexto:
    if modo == "vetorial":
        return busca_vetorial(pergunta)
    if modo == "kag":
        return resolver_kag(pergunta)
    ctx = busca_hibrida(pergunta)
    ctx.merge(text2cypher(pergunta))
    ctx.merge(resumos_relevantes(pergunta, k=2))
    return ctx


def responder(pergunta: str, modo: Modo = "hibrido",
              etapa: Callable[[str], None] | None = None) -> Resposta:
    """Responde a pergunta medindo o tempo e os tokens gastos.

    A função etapa, quando informada, recebe o nome de cada fase para a interface mostrar o progresso.
    """
    avisar = etapa or (lambda _: None)
    USAGE.reset()
    t0 = time.perf_counter()
    avisar("recuperar")
    ctx = recuperar(pergunta, modo)
    avisar("gerar")
    bruta = gerar(pergunta, ctx)
    avisar("verificar")
    ver = verificar(bruta, ctx)
    return Resposta(pergunta, modo, ctx, bruta, ver, round(time.perf_counter() - t0, 2),
                    USAGE.snapshot())
