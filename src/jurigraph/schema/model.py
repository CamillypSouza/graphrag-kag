"""Modelo LPG do domínio jurídico com labels, relações e padrões permitidos."""

from dataclasses import dataclass

ENTITY_LABEL = "Entity"


@dataclass(frozen=True)
class NodeType:
    label: str
    descricao: str


@dataclass(frozen=True)
class RelType:
    tipo: str
    descricao: str


ENTITY_TYPES: tuple[NodeType, ...] = (
    NodeType("Lei", "Norma legal (lei, decreto, código), ex.: Lei 13.709/2018 (LGPD)."),
    NodeType("Artigo", "Dispositivo de uma norma, ex.: art. 7º da LGPD."),
    NodeType("Precedente", "Súmula ou tese de repercussão geral de tribunal, ex.: Tema 987 do STF."),
    NodeType("Tribunal", "Órgão do Judiciário, ex.: STJ, STF."),
    NodeType("Orgao", "Órgão ou entidade pública/administrativa, ex.: ANPD, Procon, CGU."),
    NodeType("Conceito", "Termo jurídico definido em norma, ex.: dado pessoal, fornecedor."),
    NodeType("Sujeito", "Papel de pessoa ou ente na norma, ex.: controlador, consumidor, titular."),
    NodeType("Direito", "Direito garantido, ex.: direito de acesso aos dados, direito de arrependimento."),
    NodeType("Obrigacao", "Dever imposto a um sujeito, ex.: comunicar incidente de segurança."),
    NodeType("Sancao", "Penalidade prevista, ex.: multa de até 2% do faturamento."),
)

SEMANTIC_RELATIONS: tuple[RelType, ...] = (
    RelType("CONTEM", "Lei contém artigo."),
    RelType("CITA", "Dispositivo ou súmula faz remissão a outro dispositivo ou lei."),
    RelType("ALTERA", "Norma altera outra norma ou dispositivo."),
    RelType("REVOGA", "Norma revoga outra norma ou dispositivo."),
    RelType("REGULAMENTA", "Norma ou órgão regulamenta outra norma ou tema."),
    RelType("DEFINE", "Dispositivo define um conceito ou sujeito."),
    RelType("GARANTE", "Dispositivo garante um direito."),
    RelType("IMPOE", "Dispositivo impõe uma obrigação."),
    RelType("PREVE", "Dispositivo prevê uma sanção."),
    RelType("COMPETE_A", "Atribuição ou obrigação compete a um órgão ou sujeito."),
    RelType("APLICA_SE_A", "Direito, obrigação ou sanção se aplica a um sujeito."),
    RelType("INTERPRETA", "Precedente interpreta um dispositivo ou lei."),
    RelType("EDITADA_POR", "Precedente foi firmado por um tribunal."),
)

# padrões (origem, relação, destino) aceitos na extração, o resto é descartado
PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("Lei", "CONTEM", "Artigo"),
    ("Artigo", "CITA", "Artigo"),
    ("Artigo", "CITA", "Lei"),
    ("Precedente", "CITA", "Artigo"),
    ("Precedente", "CITA", "Lei"),
    ("Lei", "ALTERA", "Lei"),
    ("Lei", "ALTERA", "Artigo"),
    ("Artigo", "ALTERA", "Artigo"),
    ("Lei", "REVOGA", "Lei"),
    ("Artigo", "REVOGA", "Artigo"),
    ("Lei", "REGULAMENTA", "Lei"),
    ("Orgao", "REGULAMENTA", "Lei"),
    ("Orgao", "REGULAMENTA", "Conceito"),
    ("Artigo", "DEFINE", "Conceito"),
    ("Artigo", "DEFINE", "Sujeito"),
    ("Artigo", "GARANTE", "Direito"),
    ("Artigo", "IMPOE", "Obrigacao"),
    ("Artigo", "PREVE", "Sancao"),
    ("Obrigacao", "COMPETE_A", "Sujeito"),
    ("Obrigacao", "COMPETE_A", "Orgao"),
    ("Sancao", "COMPETE_A", "Orgao"),
    ("Direito", "APLICA_SE_A", "Sujeito"),
    ("Obrigacao", "APLICA_SE_A", "Sujeito"),
    ("Sancao", "APLICA_SE_A", "Sujeito"),
    ("Precedente", "INTERPRETA", "Artigo"),
    ("Precedente", "INTERPRETA", "Lei"),
    ("Precedente", "EDITADA_POR", "Tribunal"),
)

ENTITY_LABELS: frozenset[str] = frozenset(t.label for t in ENTITY_TYPES)
SEMANTIC_REL_TYPES: frozenset[str] = frozenset(r.tipo for r in SEMANTIC_RELATIONS)
PATTERN_SET: frozenset[tuple[str, str, str]] = frozenset(PATTERNS)
