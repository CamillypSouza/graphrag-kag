"""Estruturas trocadas entre as etapas da ingestão."""

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Documento:
    id: str
    titulo: str
    tipo: str
    numero: str
    ano: int | None
    fonte: str
    url: str
    licenca: str
    texto: str

    @property
    def hash(self) -> str:
        return hashlib.sha1(self.texto.encode()).hexdigest()


@dataclass
class Trecho:
    """Chunk: um artigo (ou parte dele) ou uma janela de texto."""

    id: str
    doc_id: str
    ordem: int
    rotulo: str
    texto: str
    artigo: str | None = None  # número normalizado quando o trecho é um artigo


@dataclass
class Entidade:
    key: str
    label: str
    nome: str
    descricao: str = ""
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relacao:
    origem: str
    tipo: str
    destino: str
    fonte: str  # id do chunk
    camada: str  # estrutural | semantica
    confianca: float = 1.0
    evidencia: str = ""

    @property
    def id(self) -> str:
        bruto = f"{self.origem}|{self.tipo}|{self.destino}"
        return "r-" + hashlib.sha1(bruto.encode()).hexdigest()[:10]


@dataclass
class Mencao:
    chunk_id: str
    key: str
    confianca: float = 1.0


@dataclass
class Extracao:
    """Resultado de extração de um ou mais trechos."""

    entidades: dict[str, Entidade] = field(default_factory=dict)
    relacoes: list[Relacao] = field(default_factory=list)
    mencoes: list[Mencao] = field(default_factory=list)
    descartadas: int = 0

    def add_entidade(self, e: Entidade) -> None:
        atual = self.entidades.get(e.key)
        if atual is None:
            self.entidades[e.key] = e
        elif not atual.descricao and e.descricao:
            atual.descricao = e.descricao

    def merge(self, outra: "Extracao") -> None:
        for e in outra.entidades.values():
            self.add_entidade(e)
        self.relacoes += outra.relacoes
        self.mencoes += outra.mencoes
        self.descartadas += outra.descartadas
