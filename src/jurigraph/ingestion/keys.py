"""Chaves canônicas, a mesma entidade sempre gera a mesma chave."""

import re
import unicodedata

# siglas e apelidos conhecidos e o nome canônico de cada um
ALIASES: dict[str, str] = {
    "anpd": "autoridade nacional de protecao de dados",
    "autoridade nacional": "autoridade nacional de protecao de dados",
    "stf": "supremo tribunal federal",
    "stj": "superior tribunal de justica",
    "procon": "procon",
    "cgu": "controladoria-geral da uniao",
    "controladoria geral da uniao": "controladoria-geral da uniao",
    "sndc": "sistema nacional de defesa do consumidor",
    "cgi.br": "comite gestor da internet no brasil",
    "cgi": "comite gestor da internet no brasil",
}

# apelidos de normas com o tipo e o número
NORMAS_POR_APELIDO: dict[str, tuple[str, str]] = {
    "lgpd": ("lei", "13709"),
    "lei geral de protecao de dados": ("lei", "13709"),
    "lei geral de protecao de dados pessoais": ("lei", "13709"),
    "marco civil da internet": ("lei", "12965"),
    "marco civil": ("lei", "12965"),
    "codigo de defesa do consumidor": ("lei", "8078"),
    "cdc": ("lei", "8078"),
    "lei de acesso a informacao": ("lei", "12527"),
    "lai": ("lei", "12527"),
    "constituicao federal": ("constituicao", "1988"),
    "constituicao da republica": ("constituicao", "1988"),
}


def sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c))


def normalizar_nome(nome: str) -> str:
    """Deixa em minúsculas, sem acento, sem pontuação nas pontas e com espaço simples."""
    t = sem_acento(nome).lower().strip()
    t = re.sub(r"[\"'“”‘’()\[\]]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" .,;:-")
    return ALIASES.get(t, t)


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar_nome(texto)).strip("-")


def numero_norma(numero: str) -> str:
    """Remove pontos e o ano, por exemplo '8.078/90' vira '8078'."""
    return re.sub(r"\D", "", numero.split("/")[0])


def numero_artigo(numero: str, sufixo: str | None = None) -> str:
    """Normaliza o número do artigo, por exemplo '7º' vira '7' e 4-A vira '4-a'."""
    base = re.sub(r"\D", "", numero)
    return f"{base}-{sufixo.lower()}" if sufixo else base


def norma_key(tipo: str, numero: str) -> str:
    return f"{tipo}:{numero_norma(numero)}"


def artigo_key(norma: str, artigo: str) -> str:
    """Chave do artigo a partir da chave da norma e do número já normalizado."""
    return f"artigo:{norma.replace(':', '-')}:{artigo}"


def precedente_key(tribunal: str, numero: str) -> str:
    return f"precedente:{tribunal.lower()}:{numero_norma(numero)}"


def entidade_key(label: str, nome: str) -> str:
    return f"{label.lower()}:{slug(nome)}"


def norma_por_apelido(nome: str) -> tuple[str, str] | None:
    return NORMAS_POR_APELIDO.get(normalizar_nome(nome))
