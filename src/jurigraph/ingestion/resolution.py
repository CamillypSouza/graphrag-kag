"""Resolução de entidades por chave, por fuzzy (rapidfuzz) e por embedding.

A chave canônica já resolve os casos exatos no MERGE. Aqui juntamos variações como
"titular dos dados" e "titular de dados" dentro do mesmo rótulo, sem juntar
especializações como "dado pessoal" e "dado pessoal sensível".
"""

import json
import logging
import re
from datetime import datetime
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz

from jurigraph import db
from jurigraph.config import get_settings
from jurigraph.ingestion.keys import normalizar_nome

log = logging.getLogger(__name__)
# só o embedding juntaria "segurança pública" e "segurança do Estado", por isso exige apoio léxico
APOIO_LEXICO = 70
ROTULOS_ABERTOS = ("Conceito", "Sujeito", "Direito", "Obrigacao", "Sancao", "Orgao", "Tribunal")
STOP = {"de", "da", "do", "das", "dos", "a", "o", "as", "os", "e", "em", "ao", "aos", "à", "às",
        "para", "por", "sobre", "com", "no", "na", "nos", "nas"}


@dataclass
class Candidata:
    key: str
    label: str
    nome: str
    grau: int
    embedding: list[float] | None = None


@dataclass
class Grupo:
    manter: str
    fundir: list[str]
    metodo: str
    nomes: list[str] = field(default_factory=list)


def _tokens(nome: str) -> set[str]:
    return {t for t in re.findall(r"\w+", normalizar_nome(nome)) if t not in STOP}


PLURAIS = (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("s", ""))
# Palavras que, sozinhas a mais, não mudam o conceito ("direito de acesso" = "acesso").
GENERICAS = {"direito", "dever", "obrigacao", "principio", "conceito", "regra"}


def _singular(t: str) -> str:
    if len(t) <= 4:
        return t
    for fim, troca in PLURAIS:
        if t.endswith(fim):
            return t[: -len(fim)] + troca
    return t


def _conjunto(nome: str) -> set[str]:
    return {_singular(t) for t in _tokens(nome)}


def especializacao(a: str, b: str) -> bool:
    """Verdadeiro se um nome é o outro com termos a mais (conceitos distintos)."""
    ta, tb = _conjunto(a), _conjunto(b)
    return ta != tb and (ta < tb or tb < ta) and not ((ta ^ tb) <= GENERICAS)


def substituicao(a: str, b: str) -> bool:
    """Cada nome tem termos que o outro não tem, como 'produto' e 'produtor'."""
    ta, tb = _conjunto(a), _conjunto(b)
    return bool(ta - tb) and bool(tb - ta)


def numeros_diferentes(a: str, b: str) -> bool:
    return set(re.findall(r"\d+", a)) != set(re.findall(r"\d+", b))


class _UniaoBusca:
    def __init__(self, n: int) -> None:
        self.pai = list(range(n))

    def achar(self, i: int) -> int:
        while self.pai[i] != i:
            self.pai[i] = self.pai[self.pai[i]]
            i = self.pai[i]
        return i

    def unir(self, i: int, j: int) -> None:
        self.pai[self.achar(i)] = self.achar(j)


def _pode_fundir(a: Candidata, b: Candidata) -> bool:
    """Só funde variações de plural, acento, preposição ou um termo genérico a mais."""
    return not (especializacao(a.nome, b.nome) or substituicao(a.nome, b.nome)
                or numeros_diferentes(a.nome, b.nome))


def agrupar(cands: list[Candidata], limiar_fuzzy: float, limiar_emb: float) -> list[Grupo]:
    """Grupos a fundir dentro do mesmo rótulo, o nó com mais relações é mantido."""
    if len(cands) < 2:
        return []
    uf, por_fuzzy = _UniaoBusca(len(cands)), set()
    nomes = [normalizar_nome(c.nome) for c in cands]
    embs = [c.embedding for c in cands]
    matriz = None
    if all(e is not None for e in embs):
        m = np.array(embs, dtype=np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
        matriz = m @ m.T
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            if not _pode_fundir(cands[i], cands[j]):
                continue
            if fuzz.token_sort_ratio(nomes[i], nomes[j]) >= limiar_fuzzy:
                uf.unir(i, j)
                por_fuzzy.update((i, j))
            elif (matriz is not None and matriz[i, j] >= limiar_emb
                  and fuzz.token_set_ratio(nomes[i], nomes[j]) >= APOIO_LEXICO):
                uf.unir(i, j)
    grupos: dict[int, list[int]] = {}
    for i in range(len(cands)):
        grupos.setdefault(uf.achar(i), []).append(i)
    saida = []
    for membros in grupos.values():
        if len(membros) < 2:
            continue
        membros.sort(key=lambda k: (-cands[k].grau, len(cands[k].nome)))
        metodo = "fuzzy" if por_fuzzy.issuperset(membros) else "embedding"
        saida.append(Grupo(cands[membros[0]].key, [cands[k].key for k in membros[1:]],
                           metodo, [cands[k].nome for k in membros]))
    return saida


def _candidatas(label: str) -> list[Candidata]:
    linhas = db.run(
        "MATCH (e:Entity) WHERE $label IN labels(e) "
        "RETURN e.key AS key, e.nome AS nome, e.embedding AS emb, COUNT { (e)--() } AS grau",
        label=label,
    )
    return [Candidata(r["key"], label, r["nome"], r["grau"], r["emb"]) for r in linhas]


def _fundir(g: Grupo) -> None:
    db.run(
        "MATCH (k:Entity {key: $manter}) MATCH (d:Entity) WHERE d.key IN $fundir "
        "WITH k, collect(d) AS ds "
        "SET k.aliases = coalesce(k.aliases, []) + [x IN ds | x.nome] "
        "WITH [k] + ds AS nos "
        "CALL apoc.refactor.mergeNodes(nos, {properties: 'discard', mergeRels: true}) "
        "YIELD node RETURN node.key",
        manter=g.manter, fundir=g.fundir,
    )


def resolver() -> int:
    """Resolve todos os rótulos abertos e registra cada fusão em logs/er_merges.jsonl."""
    s = get_settings()
    s.logs_dir.mkdir(exist_ok=True)
    total, execucao = 0, datetime.now().isoformat(timespec="seconds")
    with (s.logs_dir / "er_merges.jsonl").open("a", encoding="utf-8") as log_file:
        for label in ROTULOS_ABERTOS:
            for g in agrupar(_candidatas(label), s.er_fuzzy_threshold, s.er_embed_threshold):
                _fundir(g)
                total += len(g.fundir)
                log_file.write(json.dumps({"execucao": execucao, "label": label, "manter": g.manter, "fundidos": g.fundir,
                                           "nomes": g.nomes, "metodo": g.metodo},
                                          ensure_ascii=False) + "\n")
                log.info("ER %s: %s <- %s (%s)", label, g.nomes[0], g.nomes[1:], g.metodo)
    return total
