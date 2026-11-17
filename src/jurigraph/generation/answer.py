"""Geração ancorada: o LLM responde só com o contexto e cita ids em cada afirmação."""

from neo4j_graphrag.types import LLMMessage
from pydantic import Field

from jurigraph.llm import Estrito, make_llm
from jurigraph.retrieval.context import Contexto

SEM_EVIDENCIA = "Não há evidência no grafo para responder a essa pergunta."

SISTEMA = """Você é um assistente de pesquisa jurídica sobre legislação brasileira.
Responda SOMENTE com base no CONTEXTO fornecido. Não use conhecimento externo.
Divida a resposta em afirmações curtas. Cada afirmação deve citar entre 1 e 4 ids
do contexto, exatamente como aparecem: [n:...] para trechos, entidades e comunidades,
[r:...] para fatos. Prefira citar o trecho de lei que sustenta a afirmação.
Se o contexto não permitir responder, marque suficiente=false e não invente.
Isto é pesquisa, não aconselhamento jurídico."""


class Afirmacao(Estrito):
    texto: str = Field(description="uma afirmação factual, em português")
    citacoes: list[str] = Field(description="ids citados, ex.: 'n:lgpd-03-cap-iii:002' ou 'r:r-1a2b3c4d5e'")


class RespostaLLM(Estrito):
    suficiente: bool = Field(description="o contexto basta para responder?")
    afirmacoes: list[Afirmacao]


def gerar(pergunta: str, ctx: Contexto) -> RespostaLLM:
    """Resposta estruturada (afirmações + citações)."""
    if not ctx.ids_validos():
        return RespostaLLM(suficiente=False, afirmacoes=[])
    msgs = [LLMMessage(role="system", content=SISTEMA),
            LLMMessage(role="user", content=f"CONTEXTO:\n{ctx.para_prompt()}\n\nPERGUNTA: {pergunta}")]
    resp = make_llm().invoke(msgs, response_format=RespostaLLM)
    return RespostaLLM.model_validate_json(resp.content)


def normalizar_id(cit: str) -> str:
    """'[n:abc]' / 'n:abc' / 'abc' -> 'abc'."""
    c = cit.strip().strip("[]").strip()
    return c[2:] if c[:2] in ("n:", "r:") else c
