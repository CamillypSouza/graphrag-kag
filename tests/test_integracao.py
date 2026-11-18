"""Testes com o Neo4j populado para idempotência, sessão de leitura e travessia multi-hop."""

import neo4j
import pytest

from jurigraph.graph_algos.paths import caminho_minimo
from jurigraph.ingestion import writer
from jurigraph.ingestion.pipeline import executar
from jurigraph.retrieval.hybrid import busca_hibrida
from jurigraph.retrieval.text2cypher import executar_leitura

pytestmark = pytest.mark.neo4j


def test_reingestao_sem_mudanca_nao_altera_o_grafo() -> None:
    antes = writer.contagens()
    rel = executar(usar_llm=False)
    assert rel["documentos_processados"] == 0
    assert writer.contagens() == antes


def test_sessao_de_leitura_recusa_escrita() -> None:
    with pytest.raises(neo4j.exceptions.Neo4jError):
        executar_leitura("CREATE (x:Invasor) RETURN x")
    assert executar_leitura("MATCH (x:Invasor) RETURN count(x) AS n")[0]["n"] == 0


def test_busca_hibrida_traz_fatos_de_dois_saltos_com_fonte() -> None:
    ctx = busca_hibrida("Qual decreto regulamenta o Marco Civil da Internet?")
    assert ctx.trechos
    saltos = {f.salto for f in ctx.fatos.values()}
    assert {1, 2} <= saltos
    assert all(f.fontes for f in ctx.fatos.values() if f.salto == 1)


def test_caminho_minimo_entre_decreto_e_marco_civil() -> None:
    ctx = caminho_minimo("decreto:8771", "lei:12965")
    assert ctx.caminhos and ctx.caminhos[0][0] == "decreto:8771" and ctx.caminhos[0][-1] == "lei:12965"
