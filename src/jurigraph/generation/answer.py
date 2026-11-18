"""Geração da resposta usando só o contexto, com ids citados em cada afirmação."""

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
Se o contexto responder só em parte, marque suficiente=true, responda o que ele sustenta
e termine com uma afirmação dizendo o que o corpus não traz, citando o trecho mais próximo.
Marque suficiente=false apenas quando o contexto não tratar do assunto perguntado.
Nunca invente nem complete com conhecimento externo.
Isto é pesquisa, não aconselhamento jurídico."""


class Afirmacao(Estrito):
    texto: str = Field(description="uma afirmação factual, em português")
    citacoes: list[str] = Field(description="ids citados, ex.: 'n:lgpd-03-cap-iii:002' ou 'r:r-1a2b3c4d5e'")


class RespostaLLM(Estrito):
    suficiente: bool = Field(description="o contexto trata do assunto e sustenta ao menos parte da resposta?")
    afirmacoes: list[Afirmacao]


def gerar(pergunta: str, ctx: Contexto) -> RespostaLLM:
    """Resposta estruturada com afirmações e citações."""
    if not ctx.ids_validos():
        return RespostaLLM(suficiente=False, afirmacoes=[])
    msgs = [LLMMessage(role="system", content=SISTEMA),
            LLMMessage(role="user", content=f"CONTEXTO:\n{ctx.para_prompt()}\n\nPERGUNTA: {pergunta}")]
    resp = make_llm().invoke(msgs, response_format=RespostaLLM)
    return RespostaLLM.model_validate_json(resp.content)


def normalizar_id(cit: str) -> str:
    """Tira o prefixo da citação, por exemplo '[n:abc]' vira 'abc'."""
    c = cit.strip().strip("[]").strip()
    if c[:2] == "r:":  # o modelo às vezes escreve r:abc no lugar de r:r-abc
        c = c[2:]
        return c if c.startswith("r-") else "r-" + c
    return c[2:] if c[:2] == "n:" else c
