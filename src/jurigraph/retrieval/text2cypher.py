"""Text-to-Cypher: schema real do banco + few-shot jurídico + validador + EXPLAIN + 1 retentativa."""

import logging
import re
from functools import lru_cache
from typing import Any

import neo4j
from neo4j_graphrag.schema import get_schema

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.llm import make_llm
from jurigraph.retrieval.context import Contexto, EntidadeCtx, Fato, Passo
from jurigraph.retrieval.cypher_guard import validar
from jurigraph.retrieval.hybrid import adicionar_fontes

log = logging.getLogger(__name__)

EXEMPLOS = """
Pergunta: Quais direitos o art. 18 da LGPD garante?
Cypher: MATCH (a:Artigo {key: 'artigo:lei-13709:18'})-[r:GARANTE]->(d:Direito)
RETURN a.key AS artigo, r.id AS rel, d.key AS direito, d.nome AS nome LIMIT 20

Pergunta: Que artigos do Marco Civil citam a LGPD?
Cypher: MATCH (l:Lei {key: 'lei:12965'})-[:CONTEM]->(a:Artigo)-[r:CITA]->(alvo)
WHERE alvo.key = 'lei:13709' OR (alvo:Artigo AND alvo.norma = 'lei:13709')
RETURN a.key AS artigo, a.nome AS nome, r.id AS rel, alvo.key AS alvo LIMIT 20

Pergunta: Quais leis alteraram artigos da LGPD?
Cypher: MATCH (n:Lei)-[r:ALTERA]->(a:Artigo {norma: 'lei:13709'})
RETURN n.key AS norma, n.nome AS nome, count(r) AS artigos_alterados, collect(r.id)[..5] AS rels
ORDER BY artigos_alterados DESC LIMIT 10

Pergunta: Que obrigações se aplicam ao controlador?
Cypher: MATCH (o:Obrigacao)-[r:APLICA_SE_A|COMPETE_A]->(s:Sujeito)
WHERE s.nome CONTAINS 'controlador'
OPTIONAL MATCH (a:Artigo)-[r2:IMPOE]->(o)
RETURN o.key AS obrigacao, o.nome AS nome, r.id AS rel, a.key AS artigo, r2.id AS rel_artigo LIMIT 25

Pergunta: Qual decreto regulamenta o Marco Civil da Internet?
Cypher: MATCH (d:Lei)-[r:REGULAMENTA]->(l:Lei {key: 'lei:12965'})
RETURN d.key AS decreto, d.nome AS nome, r.id AS rel LIMIT 5

Pergunta: Que precedentes do STF interpretam artigos do Marco Civil?
Cypher: MATCH (p:Precedente)-[r:INTERPRETA]->(a:Artigo {norma: 'lei:12965'})
RETURN p.key AS precedente, p.nome AS nome, r.id AS rel, a.key AS artigo LIMIT 10

Pergunta: Quais sanções a LGPD prevê e quem as aplica?
Cypher: MATCH (:Lei {key: 'lei:13709'})-[:CONTEM]->(a:Artigo)-[r:PREVE]->(s:Sancao)
OPTIONAL MATCH (s)-[r2:COMPETE_A]->(o:Orgao)
RETURN a.key AS artigo, s.key AS sancao, s.nome AS nome, r.id AS rel, o.key AS orgao, r2.id AS rel_orgao LIMIT 25

Pergunta: Como o conceito de dado pessoal se liga a outros conceitos? (2 saltos)
Cypher: MATCH (c:Conceito) WHERE c.nome CONTAINS 'dado pessoal'
MATCH p = (c)-[*1..2]-(x:Entity) WHERE all(r IN relationships(p) WHERE NOT type(r) IN ['MENCIONA','CONTEM'])
RETURN c.key AS conceito, [r IN relationships(p) | r.id] AS rels, x.key AS chega_em, x.nome AS nome LIMIT 25
""".strip()

PROMPT = """Você converte perguntas sobre legislação brasileira em UMA consulta Cypher (Neo4j, Cypher 25)
somente de leitura.

Schema real do grafo:
{schema}

Convenções de chave (propriedade `key`):
- normas: 'lei:13709' (LGPD), 'lei:12965' (Marco Civil), 'lei:8078' (CDC), 'lei:12527' (LAI),
  'lei:14181' (Superendividamento), 'decreto:8771', 'decreto:7962', 'constituicao:1988'
- artigos: 'artigo:lei-13709:7', 'artigo:lei-8078:49', 'artigo:decreto-8771:3' (propriedade `norma` = chave da norma)
- precedentes: 'precedente:stf:987'
- demais entidades: busque por `nome` com CONTAINS em minúsculas.

Regras:
- Nunca escreva no banco (sem CREATE, MERGE, SET, DELETE, REMOVE, DROP).
- Sempre retorne as chaves (`key`) das entidades e o `id` das relações usadas, para citação.
- Termine com LIMIT (no máximo {limite}).
- Responda só com o Cypher, sem explicação e sem crases.

Exemplos:
{exemplos}

Pergunta: {pergunta}
Cypher:"""


@lru_cache
def schema_texto() -> str:
    """Schema lido do banco (get_schema do neo4j-graphrag), sem propriedades de embedding."""
    bruto = get_schema(db.get_driver(), sanitize=True)
    linhas = [ln for ln in bruto.splitlines() if "embedding" not in ln]
    return "\n".join(linhas)


def _limpar(resposta: str) -> str:
    texto = re.sub(r"^```(?:cypher)?|```$", "", resposta.strip(), flags=re.MULTILINE).strip()
    return texto.removeprefix("Cypher:").strip()


def _valor(v: Any, ctx: Contexto) -> Any:
    """Converte nós e relações do driver em valores serializáveis e alimenta o contexto."""
    if isinstance(v, neo4j.graph.Node):
        if "key" in v:
            label = next((l for l in v.labels if l != "Entity"), "Entity")
            ctx.entidades[v["key"]] = EntidadeCtx(v["key"], v.get("nome", v["key"]), label,
                                                  v.get("pagerank") or 0.0, v.get("descricao") or "")
            return v["key"]
        return v.get("id", v.element_id)
    if isinstance(v, neo4j.graph.Relationship):
        if v.get("id"):
            ctx.fatos[v["id"]] = Fato(v["id"], v.start_node.get("key", ""), v.type, v.end_node.get("key", ""),
                                      v.get("evidencia") or "", list(v.get("fontes") or []))
            return v["id"]
        return v.type
    if isinstance(v, neo4j.graph.Path):
        return [_valor(r, ctx) for r in v.relationships]
    if isinstance(v, list):
        return [_valor(x, ctx) for x in v]
    if isinstance(v, dict):
        return {k: _valor(x, ctx) for k, x in v.items()}
    return v


def _hidratar_ids(ctx: Contexto) -> None:
    """Ids de relação e chaves que vieram como texto viram fatos/entidades citáveis."""
    textos = {str(x) for linha in ctx.linhas_cypher for x in _achatar(linha)}
    rels = [t for t in textos if t.startswith("r-")]
    if rels:
        for r in db.run(
            "MATCH (a)-[x]->(b) WHERE x.id IN $ids RETURN x.id AS id, type(x) AS tipo, a.key AS a, "
            "b.key AS b, x.evidencia AS ev, x.fontes AS fontes", ids=rels):
            ctx.fatos.setdefault(r["id"], Fato(r["id"], r["a"], r["tipo"], r["b"], r["ev"] or "",
                                               list(r["fontes"] or [])))
    keys = {k for f in ctx.fatos.values() for k in (f.origem, f.destino)}
    keys |= {t for t in textos if re.match(r"^[a-z]+:[\w:-]+$", t)}
    keys -= set(ctx.entidades)
    if keys:
        for r in db.run(
            "MATCH (e:Entity) WHERE e.key IN $ks RETURN e.key AS key, e.nome AS nome, "
            "e.descricao AS descricao, e.pagerank AS pr, [l IN labels(e) WHERE l <> 'Entity'][0] AS label",
            ks=list(keys)):
            ctx.entidades[r["key"]] = EntidadeCtx(r["key"], r["nome"], r["label"], r["pr"] or 0.0,
                                                  r["descricao"] or "")


def _achatar(v: Any) -> list[Any]:
    if isinstance(v, dict):
        return [y for x in v.values() for y in _achatar(x)]
    if isinstance(v, list):
        return [y for x in v for y in _achatar(x)]
    return [v]


def executar_leitura(cypher: str) -> list[dict[str, Any]]:
    """EXPLAIN (valida sintaxe sem executar) e execução em sessão READ com timeout."""
    s = get_settings()
    @neo4j.unit_of_work(timeout=s.cypher_timeout_seconds)
    def _ler(tx: neo4j.ManagedTransaction) -> list[dict[str, Any]]:
        return [dict(r.items()) for r in tx.run(cypher)]

    with db.read_session() as sessao:
        sessao.run(f"EXPLAIN {cypher}").consume()
        return sessao.execute_read(_ler)


def text2cypher(pergunta: str) -> Contexto:
    """Gera, valida e executa o Cypher; em erro, tenta de novo com a mensagem no prompt."""
    s = get_settings()
    llm = make_llm()
    ctx = Contexto()
    prompt = PROMPT.format(schema=schema_texto(), limite=s.cypher_max_limit,
                           exemplos=EXEMPLOS, pergunta=pergunta)
    erro = ""
    for tentativa in (1, 2):
        texto = prompt if not erro else (
            f"{prompt}\n\nSua tentativa anterior falhou:\n{cypher}\nErro: {erro}\n"
            "Corrija e responda só com o Cypher:")
        cypher = _limpar(llm.invoke(texto).content)
        v = validar(cypher, s.cypher_max_limit)
        if not v.ok:
            erro = f"bloqueada pelo validador: {v.motivo}"
            ctx.passos.append(Passo("cypher", f"tentativa {tentativa} bloqueada", f"{cypher}\n-- {v.motivo}"))
            continue
        try:
            linhas = executar_leitura(v.cypher)
        except neo4j.exceptions.Neo4jError as exc:
            erro = exc.message or str(exc)
            ctx.passos.append(Passo("cypher", f"tentativa {tentativa} com erro", f"{v.cypher}\n-- {erro}"))
            continue
        if not linhas and tentativa == 1:
            erro = ("a consulta executou mas retornou 0 linhas; confira a direção das relações, "
                    "as chaves e se os filtros por nome não estão restritivos demais")
            ctx.passos.append(Passo("cypher", "tentativa 1 sem resultado", v.cypher))
            continue
        ctx.linhas_cypher = [_valor(linha, ctx) for linha in linhas]
        _hidratar_ids(ctx)
        adicionar_fontes(ctx)
        ctx.cyphers.append(v.cypher)
        ctx.passos.append(Passo("cypher", f"Text-to-Cypher (tentativa {tentativa})", v.cypher, len(linhas)))
        return ctx
    log.warning("text2cypher desistiu: %s", erro)
    return ctx
