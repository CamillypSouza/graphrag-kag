"""Validador de Cypher gerado por LLM: somente leitura, procedimentos permitidos e LIMIT.

É a primeira barreira; a segunda é a sessão em modo READ (o servidor recusa escrita).
"""

import re
from dataclasses import dataclass

PROIBIDAS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD|GRANT|DENY|REVOKE|ALTER|"
    r"RENAME|TERMINATE|START|STOP|USE|ENABLE|DISABLE|SHOW)\b",
    re.IGNORECASE,
)
# Qualquer chamada a procedimento ou função de namespace precisa estar aqui.
PERMITIDOS = (
    "db.index.vector.querynodes", "db.index.fulltext.querynodes", "db.labels",
    "db.relationshiptypes", "db.schema.visualization",
    "apoc.path.expand", "apoc.path.expandconfig", "apoc.path.subgraphnodes",
    "apoc.path.subgraphall", "apoc.path.spanningtree", "apoc.coll.", "apoc.text.",
    "vector.similarity.cosine",
)
NAMESPACE_RE = re.compile(r"\b((?:apoc|dbms|db|gds|genai|vector|tx)\.[\w.]+)\s*\(", re.IGNORECASE)
LIMIT_FINAL_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)


@dataclass
class Validacao:
    ok: bool
    cypher: str
    motivo: str = ""


def _sem_literais(q: str) -> str:
    """Troca strings, comentários e identificadores entre crases por espaço."""
    q = re.sub(r"/\*.*?\*/", " ", q, flags=re.S)
    q = re.sub(r"//[^\n]*", " ", q)
    q = re.sub(r"'(?:\\.|[^'\\])*'", "''", q)
    q = re.sub(r'"(?:\\.|[^"\\])*"', '""', q)
    return re.sub(r"`[^`]*`", "x", q)


def _permitido(nome: str) -> bool:
    n = nome.lower()
    return any(n == p or (p.endswith(".") and n.startswith(p)) for p in PERMITIDOS)


def validar(cypher: str, max_limit: int) -> Validacao:
    """Valida e normaliza (remove ';' final, força LIMIT <= max_limit)."""
    q = cypher.strip().rstrip(";").strip()
    if not q:
        return Validacao(False, q, "consulta vazia")
    limpo = _sem_literais(q)
    if ";" in limpo:
        return Validacao(False, q, "mais de uma instrução")
    if m := PROIBIDAS.search(limpo):
        return Validacao(False, q, f"palavra proibida: {m.group(1).upper()}")
    for nome in NAMESPACE_RE.findall(limpo):
        if not _permitido(nome):
            return Validacao(False, q, f"procedimento/função não permitido: {nome}")
    if not re.search(r"\bRETURN\b", limpo, re.IGNORECASE):
        return Validacao(False, q, "sem RETURN")
    if m := LIMIT_FINAL_RE.search(limpo):
        if int(m.group(1)) > max_limit:
            q = q[: q.rfind(m.group(0))] + f"LIMIT {max_limit}"
    else:
        q = f"{q}\nLIMIT {max_limit}"
    return Validacao(True, q)
