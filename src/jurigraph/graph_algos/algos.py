"""PageRank e Leiden no GDS (networkx como reserva) e resumos de comunidade com LLM.

A projeção usa só os nós Entity e as relações entre eles, sem direção. Chunks,
menções e comunidades ficam de fora.
"""

import argparse
import json
import logging
from typing import Any

from pydantic import Field

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.llm import Estrito, USAGE, embed_batch, make_llm

log = logging.getLogger(__name__)
GRAFO = "juri-entidades"
MIN_MEMBROS = 4


def pagerank_e_leiden_gds() -> dict[str, Any]:
    """Projeção nativa no GDS (procedimentos chamados por Cypher) e escrita de `pagerank` e `comunidade`."""
    db.run("CALL gds.graph.drop($g, false) YIELD graphName RETURN graphName", g=GRAFO)
    proj = db.run(
        "CALL gds.graph.project($g, 'Entity', {REL: {type: '*', orientation: 'UNDIRECTED'}}) "
        "YIELD nodeCount, relationshipCount RETURN nodeCount, relationshipCount", g=GRAFO)[0]
    try:
        pr = db.run("CALL gds.pageRank.write($g, {writeProperty: 'pagerank', maxIterations: 40, "
                    "dampingFactor: 0.85}) YIELD ranIterations RETURN ranIterations", g=GRAFO)[0]
        ld = db.run("CALL gds.leiden.write($g, {writeProperty: 'comunidade', randomSeed: 42, "
                    "concurrency: 1}) YIELD communityCount, modularity "
                    "RETURN communityCount, modularity", g=GRAFO)[0]
        return {"motor": "gds", "nos": proj["nodeCount"], "relacoes": proj["relationshipCount"],
                "pagerank_iteracoes": pr["ranIterations"], "comunidades": ld["communityCount"],
                "modularidade": ld["modularity"]}
    finally:
        db.run("CALL gds.graph.drop($g, false) YIELD graphName RETURN graphName", g=GRAFO)


def pagerank_e_louvain_networkx() -> dict[str, Any]:
    """Alternativa sem GDS usando networkx, com Louvain no lugar de Leiden."""
    import networkx as nx

    grafo = nx.Graph()
    grafo.add_nodes_from(r["k"] for r in db.run("MATCH (e:Entity) RETURN e.key AS k"))
    grafo.add_edges_from((r["a"], r["b"]) for r in db.run(
        "MATCH (a:Entity)-[]-(b:Entity) WHERE elementId(a) < elementId(b) RETURN a.key AS a, b.key AS b"))
    pr = nx.pagerank(grafo, alpha=0.85)
    comunidades = nx.community.louvain_communities(grafo, seed=42)
    linhas = [{"k": k, "pr": pr[k], "c": i} for i, com in enumerate(comunidades) for k in com]
    db.run("UNWIND $l AS x MATCH (e:Entity {key: x.k}) SET e.pagerank = x.pr, e.comunidade = x.c",
           l=linhas)
    return {"motor": "networkx", "nos": grafo.number_of_nodes(), "relacoes": grafo.number_of_edges(),
            "comunidades": len(comunidades),
            "modularidade": nx.community.modularity(grafo, comunidades)}


class ResumoComunidade(Estrito):
    titulo: str = Field(description="tema jurídico em até 8 palavras")
    resumo: str = Field(description="3 a 5 frases, só com base nos fatos fornecidos")


PROMPT_RESUMO = """Você resume um agrupamento (comunidade) de um grafo de conhecimento jurídico.
Use apenas os fatos abaixo; não acrescente conhecimento externo. Cite as normas pelo nome.

Entidades mais centrais (PageRank):
{entidades}

Fatos:
{fatos}
"""


def _membros_e_fatos(comunidade: int) -> tuple[list[dict], list[str]]:
    membros = db.run(
        "MATCH (e:Entity {comunidade: $c}) RETURN e.key AS key, e.nome AS nome, "
        "[l IN labels(e) WHERE l <> 'Entity'][0] AS label, e.descricao AS descricao "
        "ORDER BY e.pagerank DESC LIMIT 15", c=comunidade)
    fatos = db.run(
        "MATCH (a:Entity {comunidade: $c})-[r]->(b:Entity {comunidade: $c}) "
        "RETURN a.nome + ' -' + type(r) + '-> ' + b.nome AS f "
        "ORDER BY coalesce(a.pagerank, 0) + coalesce(b.pagerank, 0) DESC LIMIT 40", c=comunidade)
    return membros, [r["f"] for r in fatos]


def resumir_comunidades(maximo: int = 30) -> int:
    """Cria nós Community com título, resumo e embedding para as maiores comunidades."""
    from neo4j_graphrag.types import LLMMessage

    db.run("MATCH (k:Community) DETACH DELETE k")
    grupos = db.run(
        "MATCH (e:Entity) WHERE e.comunidade IS NOT NULL WITH e.comunidade AS c, count(*) AS n "
        "WHERE n >= $min RETURN c, n ORDER BY n DESC LIMIT $max", min=MIN_MEMBROS, max=maximo)
    llm = make_llm()
    feitos = []
    for g in grupos:
        membros, fatos = _membros_e_fatos(g["c"])
        prompt = PROMPT_RESUMO.format(
            entidades="\n".join(f"- {m['nome']} ({m['label']}): {m['descricao'] or ''}" for m in membros),
            fatos="\n".join(f"- {f}" for f in fatos) or "(sem fatos internos)")
        resp = llm.invoke([LLMMessage(role="user", content=prompt)], response_format=ResumoComunidade)
        r = ResumoComunidade.model_validate_json(resp.content)
        feitos.append({"id": f"comunidade:{g['c']}", "c": g["c"], "n": g["n"],
                       "titulo": r.titulo, "resumo": r.resumo})
        log.info("comunidade %s (%d membros): %s", g["c"], g["n"], r.titulo)
    vetores = embed_batch([f"{f['titulo']}. {f['resumo']}" for f in feitos])
    for f, v in zip(feitos, vetores):
        f["emb"] = v
    db.run(
        "UNWIND $fs AS f CREATE (k:Community {id: f.id, nivel: 0, titulo: f.titulo, resumo: f.resumo, "
        "tamanho: f.n, embedding: f.emb}) WITH k, f "
        "MATCH (e:Entity {comunidade: f.c}) MERGE (e)-[:PERTENCE_A]->(k)", fs=feitos)
    return len(feitos)


def executar(maximo_resumos: int = 30) -> dict[str, Any]:
    try:
        relatorio = pagerank_e_leiden_gds()
    except Exception as exc:  # se o GDS não estiver disponível usa o networkx
        log.warning("GDS indisponível (%s); usando networkx", exc)
        relatorio = pagerank_e_louvain_networkx()
    relatorio["resumos_de_comunidade"] = resumir_comunidades(maximo_resumos)
    relatorio["llm"] = USAGE.snapshot()
    return relatorio


def main() -> None:
    p = argparse.ArgumentParser(description="PageRank, comunidades e resumos")
    p.add_argument("--resumos", type=int, default=30, help="quantas comunidades resumir")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for ruidoso in ("neo4j", "httpx", "httpx2", "graphdatascience"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    print(json.dumps(executar(a.resumos), ensure_ascii=False, indent=2))
    db.close_driver()


if __name__ == "__main__":
    main()
