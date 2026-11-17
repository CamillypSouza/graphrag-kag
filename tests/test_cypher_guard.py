"""O validador bloqueia escrita e truques comuns e força LIMIT."""

import pytest

from jurigraph.retrieval.cypher_guard import validar

BLOQUEADAS = [
    "MATCH (n) DETACH DELETE n RETURN 1",
    "match (n) set n.x = 1 return n",
    "CREATE (n:Lei {key: 'x'}) RETURN n",
    "MATCH (n) /* comentário */ MERGE (m:X) RETURN n",
    "MATCH (n) RETURN n; MATCH (m) DELETE m",
    "CALL apoc.cypher.run('CREATE (x)', {}) YIELD value RETURN value",
    "RETURN apoc.cypher.runFirstColumnSingle('MATCH (n) DELETE n RETURN 1', {})",
    "CALL dbms.listConfig() YIELD name RETURN name",
    "CALL gds.graph.drop('g') YIELD graphName RETURN graphName",
    "LOAD CSV FROM 'file:///etc/passwd' AS l RETURN l",
    "MATCH (n) FOREACH (x IN [1] | REMOVE n.nome) RETURN n",
    "MATCH (n) CALL (n) { DELETE n } RETURN 1",
    "USE system SHOW USERS",
    "MATCH (n:Lei)",
]


@pytest.mark.parametrize("q", BLOQUEADAS)
def test_bloqueia(q: str) -> None:
    assert not validar(q, 50).ok


def test_palavra_proibida_dentro_de_string_e_permitida() -> None:
    v = validar("MATCH (c:Conceito) WHERE c.nome CONTAINS 'delete' RETURN c.key LIMIT 5", 50)
    assert v.ok and v.cypher.endswith("LIMIT 5")


def test_injeta_limit_quando_falta() -> None:
    v = validar("MATCH (l:Lei) RETURN l.key;", 50)
    assert v.ok and v.cypher.endswith("LIMIT 50")


def test_reduz_limit_acima_do_maximo() -> None:
    v = validar("MATCH (l:Lei) RETURN l.key LIMIT 10000", 50)
    assert v.ok and v.cypher.endswith("LIMIT 50") and "10000" not in v.cypher


def test_permite_procedimentos_de_leitura() -> None:
    q = ("CALL db.index.fulltext.queryNodes('entity_text', 'titular') YIELD node, score "
         "RETURN node.key, score")
    assert validar(q, 50).ok
    assert validar("MATCH (a:Artigo {key: 'x'}) CALL apoc.path.subgraphNodes(a, {maxLevel: 2}) "
                   "YIELD node RETURN node.key", 50).ok
