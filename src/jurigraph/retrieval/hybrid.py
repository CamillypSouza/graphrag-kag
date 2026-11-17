"""Recuperação: vetorial pura (baseline) e híbrida (vetor + fulltext + expansão multi-hop)."""

import re
from typing import Any

from neo4j_graphrag.retrievers import HybridCypherRetriever, VectorRetriever

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.llm import get_embedder
from jurigraph.retrieval.context import Contexto, EntidadeCtx, Fato, Passo, TrechoCtx

# Expansão a partir de cada chunk encontrado:
#   salto 1: Chunk -MENCIONA-> entidade semente -r1- vizinho
#   salto 2: vizinho -r2- segundo vizinho
# Leis são hubs (CONTEM centenas de artigos): não servem de semente nem de ponte.
ENT = "{.key, .nome, .descricao, .pagerank, label: [l IN labels(%s) WHERE l <> 'Entity'][0]}"
REL = ("{id: %(r)s.id, tipo: type(%(r)s), a: startNode(%(r)s).key, b: endNode(%(r)s).key, "
       "evidencia: %(r)s.evidencia, fontes: %(r)s.fontes}")
RETRIEVAL_QUERY = f"""
WITH node AS c, score, vector.similarity.cosine(node.embedding, $query_vector) AS sim
MATCH (c)-[:PARTE_DE]->(d:Document)
CALL (c) {{
  OPTIONAL MATCH (c)-[:MENCIONA]->(e:Entity) WHERE NOT e:Lei
  WITH e ORDER BY coalesce(e.pagerank, 0) DESC LIMIT 5
  OPTIONAL MATCH (e)-[r1]-(n1:Entity) WHERE NOT type(r1) IN ['MENCIONA', 'PERTENCE_A']
  WITH e, r1, n1 ORDER BY coalesce(n1.pagerank, 0) DESC LIMIT 20
  OPTIONAL CALL (e, n1) {{
    MATCH (n1)-[r2]-(n2:Entity)
    WHERE NOT n1:Lei AND n2 <> e AND NOT n2:Lei AND NOT type(r2) IN ['MENCIONA', 'PERTENCE_A', 'CONTEM']
    WITH r2, n2 ORDER BY coalesce(n2.pagerank, 0) DESC LIMIT 3
    RETURN collect({{r: {REL % {"r": "r2"}}, b: n2 {ENT % "n2"}}}) AS segundos
  }}
  RETURN collect(DISTINCT e {ENT % "e"}) AS sementes,
         collect(CASE WHEN r1 IS NULL THEN null ELSE
                 {{r: {REL % {"r": "r1"}}, b: n1 {ENT % "n1"}, segundos: segundos}} END) AS vizinhos
}}
RETURN c.id AS id, c.texto AS texto, c.rotulo AS rotulo, d.id AS doc_id, d.titulo AS titulo,
       d.url AS url, score, sim, sementes, vizinhos
"""

LUCENE_ESPECIAIS = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')


def texto_fulltext(pergunta: str) -> str:
    """Remove a sintaxe do Lucene para usar a pergunta como busca de termos."""
    return re.sub(r"\s+", " ", LUCENE_ESPECIAIS.sub(" ", pergunta)).strip() or "lei"


def cosseno(score_neo4j: float) -> float:
    """O Neo4j devolve (1 + cos) / 2; a confiança usa o cosseno bruto."""
    return round(2 * float(score_neo4j) - 1, 4)


def adicionar_fontes(ctx: Contexto, limite: int = 5) -> None:
    """Do fato ao texto: inclui os chunks de origem dos fatos mais diretos."""
    ids = [i for f in sorted(ctx.fatos.values(), key=lambda f: f.salto) for i in f.fontes]
    ids = [i for i in dict.fromkeys(ids) if i not in ctx.trechos][:limite]
    if not ids:
        return
    for r in db.run(
        "MATCH (c:Chunk)-[:PARTE_DE]->(d:Document) WHERE c.id IN $ids "
        "RETURN c.id AS id, c.texto AS texto, c.rotulo AS rotulo, d.id AS doc, d.titulo AS titulo, d.url AS url",
        ids=ids):
        ctx.trechos[r["id"]] = TrechoCtx(r["id"], r["doc"], r["titulo"], r["rotulo"], r["texto"], r["url"], 0.0)


def _entidade(m: dict[str, Any]) -> EntidadeCtx:
    return EntidadeCtx(m["key"], m.get("nome") or m["key"], m.get("label") or "Entity",
                       m.get("pagerank") or 0.0, m.get("descricao") or "")


def _fato(r: dict[str, Any], salto: int) -> Fato:
    return Fato(r["id"], r["a"], r["tipo"], r["b"], r.get("evidencia") or "",
                list(r.get("fontes") or []), salto)


def _contexto_de_registros(registros: list[Any]) -> Contexto:
    ctx = Contexto()
    for rec in registros:
        ctx.trechos[rec["id"]] = TrechoCtx(rec["id"], rec["doc_id"], rec["titulo"], rec["rotulo"],
                                           rec["texto"], rec["url"], cosseno(rec["sim"]))
        for s in rec["sementes"]:
            ctx.entidades[s["key"]] = _entidade(s)
        for v in rec["vizinhos"]:
            if not v["r"]["id"]:
                continue
            ctx.entidades[v["b"]["key"]] = _entidade(v["b"])
            ctx.fatos.setdefault(v["r"]["id"], _fato(v["r"], 1))
            for s in v["segundos"]:
                if s["r"]["id"]:
                    ctx.entidades[s["b"]["key"]] = _entidade(s["b"])
                    ctx.fatos.setdefault(s["r"]["id"], _fato(s["r"], 2))
    _completar_entidades(ctx)
    return ctx


def _completar_entidades(ctx: Contexto) -> None:
    """Garante nome e rótulo para toda ponta de fato (ex.: origem vinda do salto 2)."""
    faltam = {k for f in ctx.fatos.values() for k in (f.origem, f.destino)} - set(ctx.entidades)
    if not faltam:
        return
    for r in db.run(
        "MATCH (e:Entity) WHERE e.key IN $ks RETURN e {.key, .nome, .descricao, .pagerank, "
        "label: [l IN labels(e) WHERE l <> 'Entity'][0]} AS e", ks=list(faltam)):
        ctx.entidades[r["e"]["key"]] = _entidade(r["e"])


def busca_hibrida(pergunta: str, top_k: int | None = None) -> Contexto:
    """HybridCypherRetriever (vetor + BM25, ranker linear) com expansão de 2 saltos."""
    k = top_k or get_settings().retrieval_top_k
    ret = HybridCypherRetriever(db.get_driver(), "chunk_embedding", "chunk_text",
                                RETRIEVAL_QUERY, embedder=get_embedder())
    vetor = get_embedder().embed_query(pergunta)
    bruto = ret.get_search_results(query_text=texto_fulltext(pergunta), query_vector=vetor,
                                   top_k=k, ranker="linear", alpha=0.6)
    ctx = _contexto_de_registros(bruto.records)
    ctx.passos.append(Passo("hibrida", "vetor (chunk_embedding) + fulltext (chunk_text), ranker linear α=0,6, "
                            "expansão Cypher de 2 saltos", RETRIEVAL_QUERY.strip(), len(ctx.trechos)))
    return ctx


def busca_vetorial(pergunta: str, top_k: int | None = None) -> Contexto:
    """Baseline: só similaridade de cosseno nos chunks, sem grafo."""
    k = top_k or get_settings().retrieval_top_k
    ret = VectorRetriever(db.get_driver(), "chunk_embedding", embedder=get_embedder(),
                          return_properties=["id", "texto", "rotulo", "doc_id"])
    bruto = ret.get_search_results(query_text=pergunta, top_k=k)
    docs = {r["d"]["id"]: r["d"] for r in db.run(
        "MATCH (d:Document) WHERE d.id IN $ids RETURN d {.id, .titulo, .url} AS d",
        ids=list({rec["node"]["doc_id"] for rec in bruto.records}))}
    ctx = Contexto()
    for rec in bruto.records:
        n = rec["node"]
        d = docs.get(n["doc_id"], {"titulo": n["doc_id"], "url": ""})
        ctx.trechos[n["id"]] = TrechoCtx(n["id"], n["doc_id"], d["titulo"], n["rotulo"], n["texto"],
                                         d["url"], cosseno(rec["score"]))
    ctx.passos.append(Passo("vetorial", "db.index.vector.queryNodes em chunk_embedding", "", len(ctx.trechos)))
    return ctx
