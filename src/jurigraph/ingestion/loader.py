"""Carga dos documentos listados em data/raw/manifest.json."""

import json
from pathlib import Path

from jurigraph.ingestion.records import Documento


def carregar(pasta: Path) -> list[Documento]:
    """Lê o .json com os metadados e o .txt com o texto de cada documento."""
    ids: list[str] = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    docs = []
    for doc_id in ids:
        meta = json.loads((pasta / f"{doc_id}.json").read_text(encoding="utf-8"))
        texto = (pasta / f"{doc_id}.txt").read_text(encoding="utf-8")
        docs.append(Documento(texto=texto, **meta))
    return docs
