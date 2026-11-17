"""Cria o schema no Neo4j (pode rodar quantas vezes quiser)."""

import logging

from jurigraph import db
from jurigraph.schema.ddl import all_ddl

log = logging.getLogger(__name__)


def apply_schema() -> None:
    """Aplica constraints e índices e espera os índices ficarem ONLINE."""
    for ddl in all_ddl():
        db.run(ddl.cypher)
        log.info("ok %-10s %s", ddl.tipo, ddl.nome)
    db.run("CALL db.awaitIndexes(120)")


def existing_schema() -> dict[str, set[str]]:
    """Nomes de constraints e índices (por tipo) presentes no banco."""
    cons = {r["name"] for r in db.run("SHOW CONSTRAINTS YIELD name")}
    idx: dict[str, set[str]] = {}
    for r in db.run("SHOW INDEXES YIELD name, type, state"):
        idx.setdefault(r["type"].lower(), set()).add(r["name"])
    return {"constraint": cons, **idx}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    apply_schema()
    for tipo, nomes in sorted(existing_schema().items()):
        log.info("%s: %s", tipo, ", ".join(sorted(nomes)))
    db.close_driver()


if __name__ == "__main__":
    main()
