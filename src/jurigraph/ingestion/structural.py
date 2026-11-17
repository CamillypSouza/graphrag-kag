"""Camada estrutural (regras): normas, artigos, precedentes, remissões e alterações.

Confiança 1.0: tudo aqui sai de padrões fixos do texto legal brasileiro.
"""

import re

from jurigraph.ingestion import keys
from jurigraph.ingestion.records import Documento, Entidade, Extracao, Mencao, Relacao, Trecho

NORMA_RE = re.compile(
    r"\b(Lei Complementar|Lei|Decreto-Lei|Decreto|Medida Provisória)\s+n[º°o.]*\s*(\d[\d.]*)"
    r"(?:\s*/\s*(\d{2,4})|,\s+de\s+\d{1,2}[º°]?\s+de\s+\w+\s+de\s+(\d{4}))?",
    re.IGNORECASE,
)
ARTS_RE = re.compile(r"\barts?\.\s*((?:\d+(?:\.\d+)*\s*[º°o]?(?:-[A-Z])?(?:\s*,\s*|\s+e\s+|\s+a\s+)?)+)")
NUM_ART_RE = re.compile(r"(\d+(?:\.\d+)*)\s*[º°o]?(?:-([A-Z]))?")
ALTERACAO_RE = re.compile(
    r"\((Redação dada|Incluíd[oa]|Acrescid[oa]|Acrescentad[oa]|Revogad[oa]|Vide|Vigência)"
    r"[^)]{0,40}?(Lei Complementar|Lei|Decreto|Medida Provisória)\s+n[º°o.]*\s*(\d[\d.]*)",
    re.IGNORECASE,
)
REGULAMENTA_RE = re.compile(r"Regulamenta\s+(?:a|o)\s+(Lei|Decreto)\s+n[º°o.]*\s*(\d[\d.]*)", re.I)
JANELA_ALVO = 70
JANELA_CONSTITUICAO = 200

TIPO_NORMA = {"lei complementar": "lei", "lei": "lei", "decreto-lei": "decreto",
              "decreto": "decreto", "medida provisória": "mp"}
CONHECIDAS: dict[str, str] = {
    "lei:13709": "LGPD (Lei 13.709/2018)", "lei:12965": "Marco Civil da Internet (Lei 12.965/2014)",
    "lei:8078": "Código de Defesa do Consumidor (Lei 8.078/1990)",
    "lei:12527": "Lei de Acesso à Informação (Lei 12.527/2011)",
    "lei:14181": "Lei do Superendividamento (Lei 14.181/2021)",
    "decreto:8771": "Decreto 8.771/2016 (regulamenta o Marco Civil)",
    "decreto:7962": "Decreto 7.962/2013 (comércio eletrônico)",
    "constituicao:1988": "Constituição Federal de 1988",
}


def _norma(tipo_txt: str, numero: str) -> Entidade:
    tipo = TIPO_NORMA.get(tipo_txt.lower(), "lei")
    key = keys.norma_key(tipo, numero)
    nome = CONHECIDAS.get(key, f"{tipo_txt.title()} nº {numero}")
    return Entidade(key, "Lei", nome, props={"numero": keys.numero_norma(numero), "tipo": tipo})


def norma_do_documento(doc: Documento) -> Entidade:
    """A norma (ou o precedente) a que o documento pertence."""
    if doc.tipo == "tese":
        key = keys.precedente_key("stf", doc.numero)
        return Entidade(key, "Precedente", f"Tema {doc.numero} do STF (repercussão geral)",
                        props={"numero": doc.numero, "tribunal": "STF", "tipo": "tese"})
    e = _norma(doc.tipo, doc.numero)
    e.descricao = doc.titulo.split(" — ")[0]
    e.props["ano"] = doc.ano
    return e


def _artigo(norma: Entidade, num: str) -> Entidade:
    rotulo = f"Art. {num.replace('-', '-').upper()}"
    return Entidade(keys.artigo_key(norma.key, num), "Artigo", f"{rotulo} — {norma.nome}",
                    props={"numero": num, "norma": norma.key})


def _norma_alvo(trecho_depois: str) -> tuple[str, Entidade | None]:
    """Para uma remissão a artigo: 'propria', 'constituicao' ou outra norma."""
    janela = trecho_depois[:JANELA_ALVO]
    if re.search(r"\b(desta Lei|deste Decreto|deste Código|desta Lei Complementar)\b", janela):
        return "propria", None
    if re.search(r"\bda Constituição\b", trecho_depois[:JANELA_CONSTITUICAO]):
        return "outra", Entidade("constituicao:1988", "Lei", CONHECIDAS["constituicao:1988"],
                                 props={"numero": "1988", "tipo": "constituicao"})
    m = NORMA_RE.search(janela)
    if m:
        return "outra", _norma(m.group(1), m.group(2))
    return "propria", None


def _remissoes(t: Trecho, origem: Entidade, norma: Entidade, ext: Extracao, tipo_rel: str) -> None:
    """art. X (desta Lei | da Lei nº Y) -> CITA/INTERPRETA artigo; 'Lei nº Y' -> norma."""
    for m in ARTS_RE.finditer(t.texto):
        destino_tipo, outra = _norma_alvo(t.texto[m.end():])
        base = norma if destino_tipo == "propria" else outra
        if base is None or base.label == "Precedente":
            continue
        ext.add_entidade(base)
        for num, suf in NUM_ART_RE.findall(m.group(1)):
            alvo = _artigo(base, keys.numero_artigo(num, suf or None))
            if alvo.key == origem.key:
                continue
            ext.add_entidade(alvo)
            ext.relacoes.append(Relacao(base.key, "CONTEM", alvo.key, t.id, "estrutural"))
            ext.relacoes.append(Relacao(origem.key, tipo_rel, alvo.key, t.id, "estrutural",
                                        evidencia=m.group(0)))
            ext.mencoes.append(Mencao(t.id, alvo.key))
    em_notas = {n.start(2) for n in ALTERACAO_RE.finditer(t.texto)}
    for m in NORMA_RE.finditer(t.texto):
        alvo = _norma(m.group(1), m.group(2))
        if alvo.key == norma.key:
            continue
        ext.add_entidade(alvo)
        ext.mencoes.append(Mencao(t.id, alvo.key))
        if m.start() not in em_notas:  # nota de redação vira ALTERA, não CITA
            ext.relacoes.append(Relacao(origem.key, tipo_rel if origem.label == "Precedente" else "CITA",
                                        alvo.key, t.id, "estrutural", evidencia=m.group(0)))


def _alteracoes(t: Trecho, artigo: Entidade, ext: Extracao) -> None:
    """(Redação dada pela Lei nº X) -> Lei X ALTERA artigo; (Revogado...) -> REVOGA."""
    for m in ALTERACAO_RE.finditer(t.texto):
        nota = m.group(1).lower()
        if nota in ("vide", "vigência"):
            continue
        norma = _norma(m.group(2), m.group(3))
        ext.add_entidade(norma)
        tipo = "REVOGA" if nota.startswith("revogad") else "ALTERA"
        ext.relacoes.append(Relacao(norma.key, tipo, artigo.key, t.id, "estrutural",
                                    evidencia=m.group(0) + ")"))


def extrair(doc: Documento, trechos: list[Trecho]) -> Extracao:
    """Entidades e relações estruturais de um documento inteiro."""
    ext = Extracao()
    norma = norma_do_documento(doc)
    ext.add_entidade(norma)
    if norma.label == "Precedente":
        stf = Entidade("tribunal:supremo-tribunal-federal", "Tribunal", "Supremo Tribunal Federal")
        ext.add_entidade(stf)
        ext.relacoes.append(Relacao(norma.key, "EDITADA_POR", stf.key, trechos[0].id, "estrutural"))
    m = REGULAMENTA_RE.search(doc.texto[:1500])
    if m:
        alvo = _norma(m.group(1), m.group(2))
        ext.add_entidade(alvo)
        ext.relacoes.append(Relacao(norma.key, "REGULAMENTA", alvo.key, trechos[0].id,
                                    "estrutural", evidencia=m.group(0)))
    for t in trechos:
        ext.mencoes.append(Mencao(t.id, norma.key))
        if norma.label == "Precedente":
            _remissoes(t, norma, norma, ext, "INTERPRETA")
            continue
        if t.artigo is None:
            continue
        artigo = _artigo(norma, t.artigo)
        ext.add_entidade(artigo)
        ext.relacoes.append(Relacao(norma.key, "CONTEM", artigo.key, t.id, "estrutural"))
        ext.mencoes.append(Mencao(t.id, artigo.key))
        _remissoes(t, artigo, norma, ext, "CITA")
        _alteracoes(t, artigo, ext)
    return ext
