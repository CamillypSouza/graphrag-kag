"""Conexão com o Neo4j."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import neo4j

from jurigraph.config import get_settings

log = logging.getLogger(__name__)
# o neo4j-graphrag ainda usa db.index.fulltext.queryNodes, que gera aviso no Cypher 25
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
_driver: neo4j.Driver | None = None


def get_driver() -> neo4j.Driver:
    """Driver compartilhado, criado na primeira chamada."""
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = neo4j.GraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password.get_secret_value())
        )
        _driver.verify_connectivity()
        log.info("Conectado ao Neo4j em %s", s.neo4j_uri)
    return _driver


def close_driver() -> None:
    """Fecha o driver compartilhado."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def run(query: str, **params: Any) -> list[dict[str, Any]]:
    """Executa uma query e devolve as linhas como dicionários."""
    records, _, _ = get_driver().execute_query(
        query, params, database_=get_settings().neo4j_database
    )
    return [r.data() for r in records]


@contextmanager
def read_session(timeout: float | None = None) -> Iterator[neo4j.Session]:
    """Sessão em modo leitura, o servidor recusa qualquer escrita."""
    with get_driver().session(
        database=get_settings().neo4j_database, default_access_mode=neo4j.READ_ACCESS
    ) as session:
        yield session
