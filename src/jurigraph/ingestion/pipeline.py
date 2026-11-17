"""Ingestão completa: carga -> chunks -> extração (regras + LLM) -> MERGE -> resolução.

Idempotente e retomável: documentos cujo hash não mudou são pulados e as respostas
do LLM ficam em cache por trecho.
"""

import argparse
import asyncio
import json
import logging
import time

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.ingestion import chunking, structural, writer
from jurigraph.ingestion.loader import carregar
from jurigraph.ingestion.records import Documento, Entidade, Extracao, Trecho
from jurigraph.ingestion.resolution import resolver
from jurigraph.llm import USAGE
from jurigraph.schema.setup import apply_schema

log = logging.getLogger(__name__)


class Estado:
    """Hash de cada documento já ingerido (data/state/ingest.json)."""

    def __init__(self) -> None:
        self.arquivo = get_settings().data_dir / "state" / "ingest.json"
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.hashes: dict[str, str] = (
            json.loads(self.arquivo.read_text()) if self.arquivo.exists() else {})

    def mudou(self, doc: Documento) -> bool:
        return self.hashes.get(doc.id) != doc.hash

    def marcar(self, doc: Documento) -> None:
        self.hashes[doc.id] = doc.hash
        self.arquivo.write_text(json.dumps(self.hashes, indent=2))


def _origem(doc: Documento, t: Trecho) -> Entidade:
    """Dispositivo ao qual o trecho pertence (artigo, norma ou precedente)."""
    norma = structural.norma_do_documento(doc)
    return structural._artigo(norma, t.artigo) if t.artigo and norma.label != "Precedente" else norma


async def ingerir_documento(doc: Documento, extrator: object | None) -> Extracao:
    trechos = chunking.dividir(doc)
    writer.apagar_trechos(doc.id)
    writer.gravar_documento(doc, trechos)
    ext = structural.extrair(doc, trechos)
    if extrator is not None:
        alvos = [(t, _origem(doc, t)) for t in trechos]
        ext.merge(await extrator.extrair(alvos))  # type: ignore[attr-defined]
    writer.gravar_extracao(ext)
    return ext


def executar(limite: int | None = None, usar_llm: bool = True, forcar: bool = False) -> dict:
    """Roda a ingestão e devolve um relatório com contagens."""
    return asyncio.run(_executar(limite, usar_llm, forcar))


async def _executar(limite: int | None, usar_llm: bool, forcar: bool) -> dict:
    """Um único event loop para todo o lote (o cliente assíncrono do LLM é reaproveitado)."""
    apply_schema()
    estado = Estado()
    docs = carregar(get_settings().data_dir / "raw")[:limite]
    extrator = None
    if usar_llm:
        from jurigraph.ingestion.semantic import ExtratorSemantico

        extrator = ExtratorSemantico()
    t0, feitos, descartadas = time.time(), 0, 0
    for i, doc in enumerate(docs, 1):
        if not forcar and not estado.mudou(doc):
            continue
        ext = await ingerir_documento(doc, extrator)
        estado.marcar(doc)
        feitos += 1
        descartadas += ext.descartadas
        log.info("[%d/%d] %s: %d entidades, %d relações", i, len(docs), doc.id,
                 len(ext.entidades), len(ext.relacoes))
    novas_emb = writer.embeddings_de_entidades()
    fundidas = resolver() if feitos else 0
    if fundidas:
        writer.embeddings_de_entidades()
    return {"documentos_processados": feitos, "documentos_pulados": len(docs) - feitos,
            "embeddings_de_entidade": novas_emb, "duplicatas_resolvidas": fundidas,
            "triplas_descartadas_fora_do_schema": descartadas, "llm": USAGE.snapshot(),
            "segundos": round(time.time() - t0, 1), **writer.contagens()}


def main() -> None:
    p = argparse.ArgumentParser(description="Ingestão Text-to-Graph")
    p.add_argument("--limite", type=int, help="processa só os N primeiros documentos")
    p.add_argument("--sem-llm", action="store_true", help="só a camada estrutural")
    p.add_argument("--forcar", action="store_true", help="reprocessa mesmo sem mudança")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for ruidoso in ("neo4j", "httpx", "sentence_transformers", "neo4j_graphrag"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    relatorio = executar(a.limite, not a.sem_llm, a.forcar)
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    db.close_driver()


if __name__ == "__main__":
    main()
