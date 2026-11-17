"""O schema existe no banco e o setup é idempotente."""

import pytest

from jurigraph import db
from jurigraph.schema.ddl import all_ddl
from jurigraph.schema.model import ENTITY_LABELS, PATTERNS, SEMANTIC_REL_TYPES
from jurigraph.schema.setup import apply_schema, existing_schema


def test_padroes_usam_apenas_tipos_declarados() -> None:
    for origem, rel, destino in PATTERNS:
        assert origem in ENTITY_LABELS and destino in ENTITY_LABELS
        assert rel in SEMANTIC_REL_TYPES


def test_ddl_e_idempotente_no_texto() -> None:
    assert all("IF NOT EXISTS" in d.cypher for d in all_ddl())


@pytest.mark.neo4j
def test_schema_aplicado_e_idempotente() -> None:
    apply_schema()
    antes = existing_schema()
    apply_schema()
    assert existing_schema() == antes
    for d in all_ddl():
        assert d.nome in antes["constraint" if d.tipo == "constraint" else d.tipo], d.nome


@pytest.mark.neo4j
def test_indices_online_com_configuracao_certa() -> None:
    linhas = db.run(
        "SHOW VECTOR INDEXES YIELD name, state, options "
        "RETURN name, state, options.indexConfig AS cfg"
    )
    assert linhas, "nenhum índice vetorial"
    for r in linhas:
        assert r["state"] == "ONLINE"
        assert r["cfg"]["vector.similarity_function"].lower() == "cosine"
    ft = db.run("SHOW FULLTEXT INDEXES YIELD name, options RETURN name, options.indexConfig AS cfg")
    assert {r["cfg"]["fulltext.analyzer"] for r in ft} == {"brazilian"}
