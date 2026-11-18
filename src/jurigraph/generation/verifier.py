"""Verificação depois da geração e cálculo da confiança.

1. Confere se cada id citado existe no subgrafo recuperado.
2. Um juiz LLM confere cada afirmação contra o texto dos itens citados.
3. Confiança = 0,4 x similaridade + 0,3 x citações válidas + 0,3 x afirmações sustentadas.
Afirmações sem citação válida ou sem sustentação saem da resposta final.
"""

import re
from dataclasses import dataclass, field

from neo4j_graphrag.types import LLMMessage

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.generation.answer import SEM_EVIDENCIA, RespostaLLM, normalizar_id
from jurigraph.llm import Estrito, make_llm
from jurigraph.retrieval.context import Contexto

PESOS = {"similaridade": 0.4, "cobertura": 0.3, "sustentacao": 0.3}


@dataclass
class AfirmacaoVerificada:
    texto: str
    citacoes: list[str]
    citacoes_invalidas: list[str]
    sustentada: bool
    justificativa: str = ""


@dataclass
class Verificacao:
    afirmacoes: list[AfirmacaoVerificada] = field(default_factory=list)
    similaridade: float = 0.0
    cobertura: float = 0.0
    sustentacao: float = 0.0
    confianca: float = 0.0
    resposta_final: str = SEM_EVIDENCIA
    recusou: bool = True


class Julgamento(Estrito):
    indice: int
    sustentada: bool
    justificativa: str


class Julgamentos(Estrito):
    itens: list[Julgamento]


JUIZ = """Para cada afirmação, diga se ela é sustentada pelas EVIDÊNCIAS citadas por ela.
Sustentada = a evidência diz isso (ou implica diretamente). Generalizar, acrescentar
números, prazos ou exceções que não estão na evidência = NÃO sustentada.

{blocos}"""


def _texto_do_item(i: str, ctx: Contexto) -> str:
    if i in ctx.trechos:
        t = ctx.trechos[i]
        return f"{t.titulo}, {t.rotulo}\n{t.texto}"
    if i in ctx.fatos:
        f = ctx.fatos[i]
        base = f"{ctx.nome(f.origem)} -{f.tipo}-> {ctx.nome(f.destino)}"
        return base + (f' (evidência: "{f.evidencia}")' if f.evidencia else "") + _fontes(f.fontes)
    if i in ctx.entidades:
        e = ctx.entidades[i]
        return f"{e.nome} ({e.label}): {e.descricao}"
    return ctx.resumos.get(i, "")


def _fontes(ids: list[str]) -> str:
    """Texto dos chunks de onde o fato foi extraído."""
    if not ids:
        return ""
    linhas = db.run("MATCH (c:Chunk) WHERE c.id IN $ids RETURN c.rotulo AS r, c.texto AS t",
                    ids=ids[:2])
    return "".join(f"\n  fonte {r['r']}: {r['t'][:600]}" for r in linhas)


def _julgar(afs: list[AfirmacaoVerificada], ctx: Contexto) -> None:
    candidatas = [(k, a) for k, a in enumerate(afs) if a.citacoes]
    if not candidatas:
        return
    blocos = "\n\n".join(
        f"[{k}] AFIRMAÇÃO: {a.texto}\nEVIDÊNCIAS:\n" +
        "\n".join(f"- {_texto_do_item(i, ctx)[:1500]}" for i in a.citacoes) for k, a in candidatas)
    resp = make_llm().invoke([LLMMessage(role="user", content=JUIZ.format(blocos=blocos))],
                             response_format=Julgamentos)
    for j in Julgamentos.model_validate_json(resp.content).itens:
        if 0 <= j.indice < len(afs):
            afs[j.indice].sustentada = j.sustentada
            afs[j.indice].justificativa = j.justificativa


def verificar(resposta: RespostaLLM, ctx: Contexto) -> Verificacao:
    """Checa ids e sustentação, calcula a confiança e monta a resposta final."""
    validos = ctx.ids_validos()
    afs = []
    for a in resposta.afirmacoes:
        ids = [normalizar_id(c) for c in a.citacoes]
        texto = re.sub(r"\s*\[[nr]:[^\]]+\]", "", a.texto).strip()
        afs.append(AfirmacaoVerificada(texto, [i for i in ids if i in validos],
                                       [i for i in ids if i not in validos], False))
    v = Verificacao(afirmacoes=afs, similaridade=round(ctx.similaridade(), 3))
    if not resposta.suficiente or not afs:
        return v
    _julgar(afs, ctx)
    total_cit = sum(len(a.citacoes) + len(a.citacoes_invalidas) for a in afs)
    v.cobertura = sum(len(a.citacoes) for a in afs) / total_cit if total_cit else 0.0
    v.sustentacao = sum(a.sustentada for a in afs) / len(afs)
    v.confianca = round(PESOS["similaridade"] * v.similaridade + PESOS["cobertura"] * v.cobertura
                        + PESOS["sustentacao"] * v.sustentacao, 3)
    mantidas = [a for a in afs if a.sustentada and a.citacoes]
    if mantidas and v.confianca >= get_settings().min_evidence_score:
        v.resposta_final = " ".join(
            f"{a.texto} " + " ".join(f"[{'r' if c.startswith('r-') else 'n'}:{c}]"
                                     for c in dict.fromkeys(a.citacoes))
            for a in mantidas)
        v.recusou = False
    return v
