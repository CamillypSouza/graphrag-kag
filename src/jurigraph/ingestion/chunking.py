"""Corte em trechos: um por artigo; artigos longos e textos sem artigo viram janelas."""

import re

from jurigraph.ingestion.keys import numero_artigo
from jurigraph.ingestion.records import Documento, Trecho

ARTIGO_RE = re.compile(
    r"^Art\.\s*(\d+(?:\.\d+)*)\s*[º°o]?\s*(?:-\s*([A-Z])\b)?", re.MULTILINE
)
MAX_CHARS = 1800
JANELA = 1200


def _janelas(texto: str, tamanho: int = JANELA) -> list[str]:
    """Junta linhas até ~tamanho; a última linha de uma janela abre a seguinte."""
    linhas, partes, atual = texto.splitlines(), [], []
    for ln in linhas:
        if atual and sum(len(x) for x in atual) + len(ln) > tamanho:
            partes.append("\n".join(atual))
            atual = [atual[-1]]
        atual.append(ln)
    if atual:
        partes.append("\n".join(atual))
    return partes


def dividir(doc: Documento) -> list[Trecho]:
    """Trechos do documento, com id estável `<doc>:<ordem>`."""
    marcas = list(ARTIGO_RE.finditer(doc.texto))
    pedacos: list[tuple[str, str, str | None]] = []
    if not marcas:
        pedacos = [(f"Trecho {i + 1}", t, None) for i, t in enumerate(_janelas(doc.texto))]
    else:
        cabecalho = doc.texto[: marcas[0].start()].strip()
        for m, prox in zip(marcas, marcas[1:] + [None]):
            corpo = doc.texto[m.start(): prox.start() if prox else None].strip()
            num = numero_artigo(m.group(1), m.group(2))
            rotulo = f"Art. {m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else "")
            partes = [corpo] if len(corpo) <= MAX_CHARS else _janelas(corpo)
            for i, p in enumerate(partes):
                sufixo = f" (parte {i + 1})" if len(partes) > 1 else ""
                pedacos.append((rotulo + sufixo, p, num))
        if cabecalho and len(cabecalho) > 200:
            pedacos.insert(0, ("Cabeçalho", cabecalho, None))
    return [
        Trecho(id=f"{doc.id}:{i:03d}", doc_id=doc.id, ordem=i, rotulo=r, texto=t, artigo=a)
        for i, (r, t, a) in enumerate(pedacos)
    ]
