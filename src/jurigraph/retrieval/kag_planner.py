"""Planejador no estilo KAG que divide a pergunta em passos e encadeia os resultados.

Cada passo é uma busca, uma consulta Cypher, um caminho mínimo entre entidades ou a
leitura de resumos de comunidade. O resultado de um passo entra no objetivo dos passos
que dependem dele pelos marcadores {p1}, {p2} etc.
"""

import logging
import re
from typing import Literal

from neo4j_graphrag.types import LLMMessage
from pydantic import Field

from jurigraph.graph_algos.paths import caminho_minimo, ligar_entidades, resumos_relevantes
from jurigraph.llm import Estrito, make_llm
from jurigraph.retrieval.context import Contexto, Passo
from jurigraph.retrieval.hybrid import busca_hibrida
from jurigraph.retrieval.text2cypher import text2cypher

log = logging.getLogger(__name__)
MAX_PASSOS = 4


class PassoPlano(Estrito):
    id: str = Field(description="p1, p2, ...")
    tipo: Literal["busca", "cypher", "caminho", "comunidades"]
    objetivo: str = Field(description="o que este passo busca; pode usar {p1} para o resultado de p1")
    entidade_a: str = Field(description="só para 'caminho': nome da primeira entidade, senão vazio")
    entidade_b: str = Field(description="só para 'caminho': nome da segunda entidade, senão vazio")
    depende_de: list[str]


class Plano(Estrito):
    raciocinio: str = Field(description="uma frase sobre como a pergunta foi decomposta")
    passos: list[PassoPlano]


PLANEJADOR = f"""Você planeja a resolução de perguntas jurídicas sobre um grafo de conhecimento
(LGPD, Marco Civil da Internet, CDC, Lei de Acesso à Informação, Lei do Superendividamento,
Decretos 8.771/2016 e 7.962/2013 e temas de repercussão geral do STF).

Ferramentas (tipo do passo):
- busca: busca híbrida (vetor + texto) em trechos de lei, com expansão de 2 saltos no grafo.
- cypher: consulta estruturada (ex.: quais artigos citam X, que leis alteraram Y, que direitos o art. Z garante).
- caminho: menor caminho no grafo entre duas entidades nomeadas (preencha entidade_a e entidade_b).
- comunidades: resumos temáticos do grafo, para perguntas globais/panorâmicas.

Regras: no máximo {MAX_PASSOS} passos; perguntas simples usam 1 passo; use depende_de e {{p1}}
quando um passo precisar do resultado de outro (multi-hop)."""


def planejar(pergunta: str) -> Plano:
    resp = make_llm().invoke(
        [LLMMessage(role="system", content=PLANEJADOR), LLMMessage(role="user", content=pergunta)],
        response_format=Plano)
    plano = Plano.model_validate_json(resp.content)
    plano.passos = plano.passos[:MAX_PASSOS]
    return plano


def _resumo_resultado(ctx: Contexto, limite: int = 8) -> str:
    """Resultado curto de um passo para alimentar o seguinte."""
    nomes = [e.nome for e in sorted(ctx.entidades.values(), key=lambda e: -e.pagerank)[:limite]]
    rotulos = [f"{t.titulo}, {t.rotulo}" for t in list(ctx.trechos.values())[:3]]
    linhas = [str(l) for l in ctx.linhas_cypher[:5]]
    return "; ".join(nomes + rotulos + linhas)[:800] or "(sem resultado)"


def _executar_passo(p: PassoPlano, objetivo: str, pergunta: str) -> Contexto:
    if p.tipo == "cypher":
        return text2cypher(objetivo)
    if p.tipo == "caminho":
        a = ligar_entidades(p.entidade_a or objetivo, 1)
        b = ligar_entidades(p.entidade_b or objetivo, 1)
        if a and b and a[0].key != b[0].key:
            return caminho_minimo(a[0].key, b[0].key)
        return busca_hibrida(objetivo)
    if p.tipo == "comunidades":
        return resumos_relevantes(pergunta)
    return busca_hibrida(objetivo)


def _ordenar(passos: list[PassoPlano]) -> list[PassoPlano]:
    """Ordena os passos pelas dependências sem travar em ciclos ou ids inexistentes."""
    ids = {p.id for p in passos}
    feitos: set[str] = set()
    ordem, pendentes = [], list(passos)
    while pendentes:
        pronto = next((p for p in pendentes if set(p.depende_de) & ids <= feitos), pendentes[0])
        ordem.append(pronto)
        feitos.add(pronto.id)
        pendentes.remove(pronto)
    return ordem


def resolver_kag(pergunta: str) -> Contexto:
    """Planeja, executa os passos em ordem e junta tudo num único contexto rastreável."""
    plano = planejar(pergunta)
    total = Contexto()
    total.passos.append(Passo("plano", plano.raciocinio,
                              "\n".join(f"{p.id} [{p.tipo}] {p.objetivo} (depende de {p.depende_de})"
                                        for p in plano.passos), len(plano.passos)))
    resultados: dict[str, str] = {}
    for p in _ordenar(plano.passos):
        objetivo = re.sub(r"\{(p\d+)\}", lambda m: resultados.get(m.group(1), ""), p.objetivo)
        try:
            ctx = _executar_passo(p, objetivo, pergunta)
        except Exception as exc:  # um passo ruim não derruba o plano inteiro
            log.warning("passo %s falhou: %s", p.id, exc)
            total.passos.append(Passo(p.tipo, f"{p.id} falhou", str(exc)))
            continue
        resultados[p.id] = _resumo_resultado(ctx)
        for passo in ctx.passos:
            passo.descricao = f"{p.id}: {passo.descricao}"
        total.merge(ctx)
    return total
