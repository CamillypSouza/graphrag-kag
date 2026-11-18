"""Camada semântica com o LLMEntityRelationExtractor do neo4j-graphrag e o schema jurídico.

O dispositivo do trecho já vem da camada estrutural e entra no prompt com o id 'art'.
O LLM só cria nós dos tipos abertos (Conceito, Sujeito, Direito etc.) e qualquer tripla
fora de PATTERNS é descartada. As respostas ficam em cache por trecho, modelo e versão do prompt.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from neo4j_graphrag.components.entity_relation_extractor import (
    LLMEntityRelationExtractor, OnError,
)
from neo4j_graphrag.components.schema import (
    GraphSchema, NodeType, PropertyType, RelationshipType,
)
from neo4j_graphrag.components.types import Neo4jGraph, TextChunk
from neo4j_graphrag.generation.prompts import ERExtractionTemplate

from jurigraph.config import get_settings
from jurigraph.ingestion import keys
from jurigraph.ingestion.records import Entidade, Extracao, Mencao, Relacao, Trecho
from jurigraph.llm import make_llm
from jurigraph.schema.model import ENTITY_TYPES, PATTERN_SET, SEMANTIC_RELATIONS

log = logging.getLogger(__name__)
PROMPT_VERSAO = "v2"
ABERTOS = ("Conceito", "Sujeito", "Direito", "Obrigacao", "Sancao", "Orgao", "Tribunal")
ID_ORIGEM = "art"


class ExtracaoJuridicaTemplate(ERExtractionTemplate):
    DEFAULT_TEMPLATE = """Você extrai um grafo de conhecimento de textos jurídicos brasileiros.

A primeira linha do trecho indica o dispositivo de origem. Ele JÁ EXISTE no grafo
com id "art". Use "art" como origem das relações que partem do dispositivo
(DEFINE, GARANTE, IMPOE, PREVE). Não crie nós de Lei nem de Artigo.

Crie apenas nós destes tipos, com as propriedades "nome" (curto, no singular,
como aparece na lei) e "descricao" (uma frase fiel ao texto):
{schema}

Regras:
- Extraia só o que o texto afirma. Não use conhecimento externo.
- Cada relação deve ter a propriedade "evidencia": trecho literal curto (até 15 palavras).
- Respeite a direção e os pares (origem, tipo, destino) permitidos em "patterns".
- Prefira poucas entidades relevantes (no máximo 8) a muitas genéricas.
- Nomes canônicos e autoexplicativos: "direito de acesso aos dados", não "direito a obter".
- Órgãos públicos (ANPD, "autoridade nacional", Procon, CGU) são Orgao, nunca Conceito.

Exemplo de saída:
{examples}

Trecho:
{text}
"""
    EXPECTED_INPUTS = ["text"]


EXEMPLO = json.dumps({
    "nodes": [
        {"id": "art", "label": "Artigo", "properties": {"nome": "Art. 18"}},
        {"id": "1", "label": "Direito", "properties": {
            "nome": "direito de acesso aos dados", "descricao": "O titular pode obter do controlador acesso aos seus dados."}},
        {"id": "2", "label": "Sujeito", "properties": {
            "nome": "titular", "descricao": "Pessoa natural a quem se referem os dados pessoais."}},
    ],
    "relationships": [
        {"type": "GARANTE", "start_node_id": "art", "end_node_id": "1",
         "properties": {"evidencia": "o titular dos dados pessoais tem direito a obter"}},
        {"type": "APLICA_SE_A", "start_node_id": "1", "end_node_id": "2",
         "properties": {"evidencia": "o titular dos dados pessoais tem direito"}},
    ],
}, ensure_ascii=False)


def graph_schema() -> GraphSchema:
    """Schema passado ao LLM com os tipos abertos e o dispositivo de origem."""
    props = [PropertyType(name="nome", type="STRING"), PropertyType(name="descricao", type="STRING")]
    nos = [NodeType(label=t.label, description=t.descricao, properties=props)
           for t in ENTITY_TYPES if t.label in ABERTOS or t.label in ("Artigo", "Precedente")]
    rels = [RelationshipType(label=r.tipo, description=r.descricao,
                             properties=[PropertyType(name="evidencia", type="STRING")])
            for r in SEMANTIC_RELATIONS]
    padroes = [p for p in PATTERN_SET if p[0] in ABERTOS + ("Artigo",) and p[2] in ABERTOS]
    return GraphSchema(node_types=tuple(nos), relationship_types=tuple(rels),
                       patterns=tuple(sorted(padroes)), additional_node_types=False,
                       additional_relationship_types=False, additional_patterns=False)


class Cache:
    """Cache das respostas do LLM em JSONL para não pagar de novo ao reprocessar."""

    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo
        self.dados: dict[str, dict] = {}
        if arquivo.exists():
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                item = json.loads(linha)
                self.dados[item["k"]] = item["g"]

    @staticmethod
    def chave(t: Trecho) -> str:
        base = f"{get_settings().llm_model}|{PROMPT_VERSAO}|{t.id}|{t.texto}"
        return hashlib.sha1(base.encode()).hexdigest()

    def get(self, t: Trecho) -> Neo4jGraph | None:
        g = self.dados.get(self.chave(t))
        return Neo4jGraph.model_validate(g) if g is not None else None

    def put(self, t: Trecho, g: Neo4jGraph) -> None:
        k = self.chave(t)
        self.dados[k] = g.model_dump()
        with self.arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": k, "g": self.dados[k]}, ensure_ascii=False) + "\n")


def converter(g: Neo4jGraph, t: Trecho, origem: Entidade) -> Extracao:
    """Mapeia o grafo do LLM para chaves canônicas e descarta o que foge do schema."""
    ext = Extracao()
    mapa: dict[str, Entidade] = {ID_ORIGEM: origem}  # o LLM nem sempre lista "art" em nodes
    for n in g.nodes:
        if n.id == ID_ORIGEM or n.label in ("Artigo", "Precedente"):
            mapa[n.id] = origem
            continue
        nome = str(n.properties.get("nome") or "").strip()
        if n.label not in ABERTOS or len(nome) < 3:
            ext.descartadas += 1
            continue
        e = Entidade(keys.entidade_key(n.label, nome), n.label, nome,
                     str(n.properties.get("descricao") or "").strip())
        mapa[n.id] = e
        ext.add_entidade(e)
        ext.mencoes.append(Mencao(t.id, e.key, 0.8))
    for r in g.relationships:
        a, b = mapa.get(r.start_node_id), mapa.get(r.end_node_id)
        if a is None or b is None or (a.label, r.type, b.label) not in PATTERN_SET:
            ext.descartadas += 1
            continue
        ext.relacoes.append(Relacao(a.key, r.type, b.key, t.id, "semantica", 0.8,
                                    str(r.properties.get("evidencia") or "")[:200]))
    return ext


class ExtratorSemantico:
    def __init__(self, concorrencia: int = 6) -> None:
        self.extrator = LLMEntityRelationExtractor(
            llm=make_llm(), prompt_template=ExtracaoJuridicaTemplate(),
            create_lexical_graph=False, on_error=OnError.IGNORE)
        self.schema = graph_schema()
        self.cache = Cache(get_settings().data_dir / "state" / "llm_extracao.jsonl")
        self.sem = asyncio.Semaphore(concorrencia)

    async def _um(self, t: Trecho, origem: Entidade) -> Extracao:
        g = self.cache.get(t)
        if g is None:
            texto = f"[Dispositivo de origem (id art, {origem.label}): {origem.nome}]\n{t.texto}"
            async with self.sem:
                g = await self.extrator.extract_for_chunk(
                    self.schema, EXEMPLO, TextChunk(text=texto, index=t.ordem))
            if g.nodes:  # resposta vazia pode ser falha temporária, então não vai para o cache
                self.cache.put(t, g)
        return converter(g, t, origem)

    async def extrair(self, itens: list[tuple[Trecho, Entidade]]) -> Extracao:
        """Extrai todos os trechos em paralelo, com limite de chamadas simultâneas."""
        total = Extracao()
        for parcial in await asyncio.gather(*(self._um(t, o) for t, o in itens)):
            total.merge(parcial)
        return total
