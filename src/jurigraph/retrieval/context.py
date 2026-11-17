"""Contexto recuperado: trechos, fatos (relações), entidades e o rastro de como foi obtido.

Tudo que o LLM pode citar tem um id: [n:<chunk ou chave de entidade>] ou [r:<id da relação>].
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrechoCtx:
    id: str
    doc_id: str
    titulo: str
    rotulo: str
    texto: str
    url: str
    score: float  # similaridade de cosseno com a pergunta (0 quando não se aplica)


@dataclass
class EntidadeCtx:
    key: str
    nome: str
    label: str
    pagerank: float = 0.0
    descricao: str = ""


@dataclass
class Fato:
    id: str
    origem: str
    tipo: str
    destino: str
    evidencia: str = ""
    fontes: list[str] = field(default_factory=list)
    salto: int = 1


@dataclass
class Passo:
    """Um passo do rastro (busca, Cypher, algoritmo) exibido na interface."""

    tipo: str
    descricao: str
    detalhe: str = ""
    resultados: int = 0


@dataclass
class Contexto:
    trechos: dict[str, TrechoCtx] = field(default_factory=dict)
    entidades: dict[str, EntidadeCtx] = field(default_factory=dict)
    fatos: dict[str, Fato] = field(default_factory=dict)
    linhas_cypher: list[dict[str, Any]] = field(default_factory=list)
    resumos: dict[str, str] = field(default_factory=dict)  # comunidade -> resumo
    caminhos: list[list[str]] = field(default_factory=list)  # ids de nós e relações em ordem
    cyphers: list[str] = field(default_factory=list)
    passos: list[Passo] = field(default_factory=list)

    def ids_validos(self) -> set[str]:
        return (set(self.trechos) | set(self.entidades) | set(self.fatos) | set(self.resumos))

    def similaridade(self) -> float:
        """Média das 3 maiores similaridades; contexto só estrutural conta 1.0 se não vazio."""
        scores = sorted((t.score for t in self.trechos.values() if t.score > 0), reverse=True)[:3]
        if scores:
            return sum(scores) / len(scores)
        return 1.0 if (self.fatos or self.linhas_cypher) else 0.0

    def merge(self, outro: "Contexto") -> None:
        for t in outro.trechos.values():
            atual = self.trechos.get(t.id)
            if atual is None or t.score > atual.score:
                self.trechos[t.id] = t
        self.entidades.update(outro.entidades)
        for f in outro.fatos.values():
            self.fatos.setdefault(f.id, f)
        self.linhas_cypher += outro.linhas_cypher
        self.resumos.update(outro.resumos)
        self.caminhos += outro.caminhos
        self.cyphers += outro.cyphers
        self.passos += outro.passos

    def nome(self, key: str) -> str:
        e = self.entidades.get(key)
        return e.nome if e else key

    def para_prompt(self, max_trechos: int = 10, max_fatos: int = 60) -> str:
        """Contexto serializado com os ids citáveis."""
        partes = []
        if self.resumos:
            partes.append("## Resumos de comunidades do grafo")
            partes += [f"[n:{k}] {v}" for k, v in self.resumos.items()]
        trechos = sorted(self.trechos.values(), key=lambda t: -t.score)[:max_trechos]
        if trechos:
            partes.append("## Trechos de documentos")
            partes += [f"[n:{t.id}] ({t.titulo} — {t.rotulo})\n{t.texto}" for t in trechos]
        if self.fatos:
            partes.append("## Fatos do grafo (origem -TIPO-> destino)")
            ordem = sorted(self.fatos.values(), key=lambda f: (f.salto, f.tipo))[:max_fatos]
            partes += [f"[r:{f.id}] [n:{f.origem}] {self.nome(f.origem)} -{f.tipo}-> "
                       f"[n:{f.destino}] {self.nome(f.destino)}"
                       + (f' (evidência: "{f.evidencia}")' if f.evidencia else "") for f in ordem]
        if self.linhas_cypher:
            partes.append("## Resultado de consulta Cypher")
            partes += [str(linha) for linha in self.linhas_cypher[:30]]
        return "\n\n".join(partes) if partes else "(contexto vazio)"
