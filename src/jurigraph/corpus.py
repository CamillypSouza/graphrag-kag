"""Baixa o corpus público (planalto.gov.br e STF) e grava em data/raw.

Cada lei é cortada por CAPÍTULO; cada capítulo vira um documento com metadados.
Texto revogado (riscado no site) é descartado; notas de redação são mantidas,
pois viram relações ALTERA/CITA.
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from jurigraph.config import get_settings

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (projeto academico GraphRAG; corpus de leis publicas)"
PAUSA_S = 6.0
MIN_CHARS = 400

PLANALTO = "https://www.planalto.gov.br/ccivil_03"
LEIS: list[dict[str, str | int]] = [
    {"id": "lgpd", "titulo": "Lei Geral de Proteção de Dados Pessoais", "tipo": "lei",
     "numero": "13709", "ano": 2018, "url": f"{PLANALTO}/_ato2015-2018/2018/lei/l13709compilado.htm"},
    {"id": "mci", "titulo": "Marco Civil da Internet", "tipo": "lei", "numero": "12965",
     "ano": 2014, "url": f"{PLANALTO}/_ato2011-2014/2014/lei/l12965.htm"},
    {"id": "cdc", "titulo": "Código de Defesa do Consumidor", "tipo": "lei", "numero": "8078",
     "ano": 1990, "url": f"{PLANALTO}/leis/l8078compilado.htm"},
    {"id": "lai", "titulo": "Lei de Acesso à Informação", "tipo": "lei", "numero": "12527",
     "ano": 2011, "url": f"{PLANALTO}/_ato2011-2014/2011/lei/l12527.htm"},
    {"id": "superendividamento", "titulo": "Lei do Superendividamento", "tipo": "lei",
     "numero": "14181", "ano": 2021, "url": f"{PLANALTO}/_ato2019-2022/2021/lei/l14181.htm"},
    {"id": "dec8771", "titulo": "Decreto que regulamenta o Marco Civil da Internet",
     "tipo": "decreto", "numero": "8771", "ano": 2016,
     "url": f"{PLANALTO}/_ato2015-2018/2016/decreto/d8771.htm"},
    {"id": "dec7962", "titulo": "Decreto do Comércio Eletrônico (regulamenta o CDC)",
     "tipo": "decreto", "numero": "7962", "ano": 2013,
     "url": f"{PLANALTO}/_ato2011-2014/2013/decreto/d7962.htm"},
]
STF_TEMA_URL = "https://portal.stf.jus.br/jurisprudenciaRepercussao/tema.asp?num={num}"
# Candidatos; só ficam os que citam alguma lei do corpus (filtro em _tema_relevante).
STF_TEMAS = [987, 533, 210, 1141, 1075, 1066, 786, 1093, 1248, 362, 1056]
TERMOS_RELEVANTES = ("12.965", "13.709", "8.078", "12.527", "consumidor", "dados pessoais",
                     "marco civil", "provedor", "acesso à informação")


@dataclass
class RawDoc:
    id: str
    titulo: str
    tipo: str
    numero: str
    ano: int | None
    fonte: str
    url: str
    licenca: str
    texto: str


def _get(url: str, tentativas: int = 5) -> bytes:
    """GET com pausa entre requisições e backoff exponencial em falha."""
    for i in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            time.sleep(PAUSA_S)
            return r.content
        except requests.RequestException as exc:
            espera = PAUSA_S * 2 ** (i + 1)
            log.warning("falha em %s (%s); nova tentativa em %.0fs", url, exc, espera)
            time.sleep(espera)
    raise RuntimeError(f"não consegui baixar {url}")


def _get_com_cache(url: str) -> str:
    """Baixa uma vez e guarda os bytes em data/state/html, para não repetir requisições."""
    pasta = get_settings().data_dir / "state" / "html"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".bin")
    if not arquivo.exists():
        arquivo.write_bytes(_get(url))
    return decodificar(arquivo.read_bytes())


def decodificar(conteudo: bytes) -> str:
    """UTF-8 quando válido; senão windows-1252 (padrão das páginas do planalto)."""
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("windows-1252", errors="replace")


BLOCOS = ["p", "h1", "h2", "h3", "h4", "h5", "li", "td"]


def html_para_texto(html: str, por_paragrafo: bool = True) -> str:
    """Texto limpo sem trechos revogados (riscados); um parágrafo por linha se pedido."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "strike", "s", "del"]):
        tag.decompose()
    blocos = [b for b in soup.find_all(BLOCOS) if not b.find(BLOCOS)] if por_paragrafo else []
    linhas = [b.get_text(" ") for b in blocos] or soup.get_text("\n").splitlines()
    limpas = [re.sub(r"\s+([;,.)])", r"\1", re.sub(r"\s+", " ", ln)).strip() for ln in linhas]
    return "\n".join(ln for ln in limpas if ln)


CAPITULO_RE = re.compile(r"^CAP[IÍ]TULO\s+([IVXLC]+(?:-[A-Z])?)\b.*$", re.MULTILINE)


def dividir_por_capitulo(texto: str) -> list[tuple[str, str]]:
    """Divide em (rótulo, texto) por CAPÍTULO; capítulos curtos juntam com o seguinte."""
    marcas = list(CAPITULO_RE.finditer(texto))
    if not marcas:
        return [("integral", texto)]
    partes = [("preambulo", texto[: marcas[0].start()])]
    for m, prox in zip(marcas, marcas[1:] + [None]):
        partes.append((f"cap-{m.group(1).lower()}", texto[m.start(): prox.start() if prox else None]))
    juntas: list[tuple[str, str]] = []
    pendente = ""
    for rotulo, trecho in partes:
        pendente += trecho
        if len(pendente) >= MIN_CHARS:
            juntas.append((rotulo, pendente.strip()))
            pendente = ""
    if pendente and juntas:
        juntas[-1] = (juntas[-1][0], juntas[-1][1] + "\n" + pendente.strip())
    return juntas


def baixar_leis() -> list[RawDoc]:
    """Uma lista de documentos, um por capítulo de cada norma."""
    docs: list[RawDoc] = []
    for lei in LEIS:
        texto = html_para_texto(_get_com_cache(str(lei["url"])))
        for seq, (rotulo, trecho) in enumerate(dividir_por_capitulo(texto), start=1):
            titulo_cap = trecho.splitlines()[0] if rotulo.startswith("cap") else rotulo
            docs.append(RawDoc(
                id=f"{lei['id']}-{seq:02d}-{rotulo}", titulo=f"{lei['titulo']} — {titulo_cap}",
                tipo=str(lei["tipo"]), numero=str(lei["numero"]), ano=int(lei["ano"]),
                fonte="Planalto (Presidência da República)", url=str(lei["url"]),
                licenca="Domínio público: texto normativo (Lei 9.610/98, art. 8º, IV)",
                texto=trecho))
        log.info("%s: %d documentos", lei["id"], sum(d.id.startswith(f"{lei['id']}-") for d in docs))
    return docs


def _tema_relevante(texto: str) -> bool:
    baixo = texto.lower()
    return any(t in baixo for t in TERMOS_RELEVANTES)


def baixar_temas_stf() -> list[RawDoc]:
    """Temas de repercussão geral do STF que tratam das leis do corpus."""
    docs: list[RawDoc] = []
    for num in STF_TEMAS:
        url = STF_TEMA_URL.format(num=num)
        bruto = html_para_texto(_get_com_cache(url), por_paragrafo=False)
        inicio, fim = bruto.find("Tema:"), bruto.find("Mapa do Site")
        texto = bruto[inicio:fim].strip() if inicio >= 0 else ""
        if not texto or not _tema_relevante(texto):
            log.info("tema %s ignorado (fora do escopo do corpus)", num)
            continue
        docs.append(RawDoc(
            id=f"stf-tema-{num}", titulo=f"STF — Tema {num} de Repercussão Geral", tipo="tese",
            numero=str(num), ano=None, fonte="Supremo Tribunal Federal", url=url,
            licenca="Domínio público: decisão judicial (Lei 9.610/98, art. 8º, IV)", texto=texto))
    log.info("stf: %d temas relevantes", len(docs))
    return docs


def gravar(docs: list[RawDoc], pasta: Path) -> None:
    """Grava .txt + .json por documento, o índice FONTES.md e o manifest.json (lista oficial)."""
    pasta.mkdir(parents=True, exist_ok=True)
    for d in docs:
        (pasta / f"{d.id}.txt").write_text(d.texto, encoding="utf-8")
        meta = {k: v for k, v in asdict(d).items() if k != "texto"}
        (pasta / f"{d.id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    linhas = ["# Fontes do corpus", "", "| Documento | Tipo | Fonte | Licença | URL |", "|---|---|---|---|---|"]
    linhas += [f"| {d.titulo} | {d.tipo} | {d.fonte} | {d.licenca} | {d.url} |" for d in docs]
    (pasta / "FONTES.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    manifest = [d.id for d in docs]
    (pasta / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    docs = baixar_leis() + baixar_temas_stf()
    gravar(docs, get_settings().data_dir / "raw")
    log.info("total: %d documentos em data/raw", len(docs))


if __name__ == "__main__":
    main()
