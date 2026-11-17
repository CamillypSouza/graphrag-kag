"""Ligação de entidades citadas na pergunta, caminho mínimo e resumos de comunidade."""

from jurigraph import db
from jurigraph.llm import get_embedder
from jurigraph.retrieval.context import Contexto, EntidadeCtx, Fato, Passo
from jurigraph.retrieval.hybrid import adicionar_fontes, texto_fulltext

CAMINHO = """
MATCH (a:Entity {key: $a}), (b:Entity {key: $b})
MATCH p = shortestPath((a)-[*..6]-(b))
WHERE all(n IN nodes(p) WHERE n:Entity)
  AND none(r IN relationships(p) WHERE type(r) IN ['MENCIONA', 'PERTENCE_A'])
RETURN [n IN nodes(p) | n {.key, .nome, .descricao, .pagerank,
          label: [l IN labels(n) WHERE l <> 'Entity'][0]}] AS nos,
       [r IN relationships(p) | {id: r.id, tipo: type(r), a: startNode(r).key, b: endNode(r).key,
          evidencia: r.evidencia, fontes: r.fontes}] AS rels
"""


def ligar_entidades(texto: str, k: int = 3) -> list[EntidadeCtx]:
    """Entidades do grafo mais prováveis para um texto (fulltext + vetor em entity_*)."""
    termos = texto_fulltext(texto)
    linhas = db.run(
        "CALL () { CALL db.index.fulltext.queryNodes('entity_text', $t, {limit: $k}) YIELD node, score "
        "  RETURN node, score / (score + 1.0) AS s "
        "  UNION "
        "  CALL db.index.vector.queryNodes('entity_embedding', $k, $v) YIELD node, score "
        "  RETURN node, score AS s } "
        "WITH node, max(s) AS s ORDER BY s DESC LIMIT $k "
        "RETURN node {.key, .nome, .descricao, .pagerank, "
        "label: [l IN labels(node) WHERE l <> 'Entity'][0]} AS e",
        t=termos, k=k, v=get_embedder().embed_query(texto))
    return [EntidadeCtx(r["e"]["key"], r["e"]["nome"], r["e"]["label"], r["e"]["pagerank"] or 0.0,
                        r["e"]["descricao"] or "") for r in linhas]


def caminho_minimo(a: str, b: str) -> Contexto:
    """Menor caminho entre duas entidades, só por relações semânticas/estruturais."""
    ctx = Contexto()
    linhas = db.run(CAMINHO, a=a, b=b)
    if not linhas:
        ctx.passos.append(Passo("caminho", f"sem caminho entre {a} e {b}", CAMINHO.strip()))
        return ctx
    nos, rels = linhas[0]["nos"], linhas[0]["rels"]
    for n in nos:
        ctx.entidades[n["key"]] = EntidadeCtx(n["key"], n["nome"], n["label"], n["pagerank"] or 0.0,
                                              n["descricao"] or "")
    for r in rels:
        ctx.fatos[r["id"]] = Fato(r["id"], r["a"], r["tipo"], r["b"], r["evidencia"] or "",
                                  list(r["fontes"] or []))
    ordem = [nos[0]["key"]]
    for r, n in zip(rels, nos[1:]):
        ordem += [r["id"], n["key"]]
    ctx.caminhos.append(ordem)
    adicionar_fontes(ctx, limite=len(rels) + 1)
    ctx.cyphers.append(CAMINHO.strip())
    ctx.passos.append(Passo("caminho", f"caminho mínimo {nos[0]['nome']} → {nos[-1]['nome']} "
                            f"({len(rels)} saltos)", CAMINHO.strip(), len(rels)))
    return ctx


def resumos_relevantes(pergunta: str, k: int = 3) -> Contexto:
    """Resumos de comunidade mais próximos da pergunta (perguntas globais)."""
    ctx = Contexto()
    for r in db.run(
        "CALL db.index.vector.queryNodes('community_embedding', $k, $v) YIELD node, score "
        "RETURN node.id AS id, node.titulo AS titulo, node.resumo AS resumo, score",
        k=k, v=get_embedder().embed_query(pergunta)):
        ctx.resumos[r["id"]] = f"{r['titulo']}: {r['resumo']}"
    ctx.passos.append(Passo("comunidades", "resumos de comunidade (Leiden) por similaridade",
                            "db.index.vector.queryNodes('community_embedding', ...)", len(ctx.resumos)))
    return ctx
