"""Chunking, chaves, regras estruturais e resolução (sem rede e sem banco)."""

from jurigraph.ingestion import keys
from jurigraph.ingestion.chunking import dividir
from jurigraph.ingestion.records import Documento
from jurigraph.ingestion.resolution import Candidata, agrupar, especializacao, substituicao
from jurigraph.ingestion.structural import extrair

TEXTO = """CAPÍTULO III DOS DIREITOS DO TITULAR
Art. 17. Toda pessoa natural tem assegurada a titularidade de seus dados pessoais.
Art. 18. O titular dos dados pessoais tem direito a obter do controlador, nos termos do art. 7º desta Lei e do art. 43 da Lei nº 8.078, de 11 de setembro de 1990:
I - confirmação da existência de tratamento; (Redação dada pela Lei nº 13.853, de 2019)
Art. 18-A. Texto incluído.
"""


def _doc() -> Documento:
    return Documento(id="lgpd-03", titulo="Lei Geral de Proteção de Dados Pessoais — CAP III",
                     tipo="lei", numero="13709", ano=2018, fonte="Planalto", url="u",
                     licenca="dp", texto=TEXTO)


def test_chunk_por_artigo_com_id_estavel() -> None:
    trechos = dividir(_doc())
    assert [t.artigo for t in trechos] == ["17", "18", "18-a"]
    assert [t.id for t in trechos] == ["lgpd-03:000", "lgpd-03:001", "lgpd-03:002"]
    assert [t.id for t in dividir(_doc())] == [t.id for t in trechos]


def test_chaves_canonicas() -> None:
    assert keys.norma_key("lei", "13.709") == "lei:13709"
    assert keys.numero_artigo("7º") == "7"
    assert keys.numero_artigo("4", "A") == "4-a"
    assert keys.entidade_key("Orgao", "ANPD") == keys.entidade_key(
        "Orgao", "Autoridade Nacional de Proteção de Dados")
    assert keys.norma_por_apelido("LGPD") == ("lei", "13709")


def test_regras_extraem_remissoes_e_alteracoes() -> None:
    ext = extrair(_doc(), dividir(_doc()))
    triplas = {(r.origem, r.tipo, r.destino) for r in ext.relacoes}
    assert ("lei:13709", "CONTEM", "artigo:lei-13709:18") in triplas
    assert ("artigo:lei-13709:18", "CITA", "artigo:lei-13709:7") in triplas
    assert ("artigo:lei-13709:18", "CITA", "artigo:lei-8078:43") in triplas
    assert ("lei:13853", "ALTERA", "artigo:lei-13709:18") in triplas
    assert not any(t[2] == "lei:13853" and t[1] == "CITA" for t in triplas)


def test_especializacao_e_substituicao_nao_fundem() -> None:
    assert especializacao("dado pessoal", "dado pessoal sensível")
    assert not especializacao("titular dos dados", "titular de dados")
    assert not especializacao("acesso aos dados", "direito de acesso aos dados")
    assert substituicao("produto", "produtor")
    assert substituicao("Ministério Público da União", "Ministério Público dos Estados")
    assert not substituicao("provedor de aplicações", "provedor de aplicação")


def test_agrupar_por_fuzzy_e_embedding_com_travas() -> None:
    cands = [
        Candidata("s:1", "Sujeito", "titular dos dados", 5, [1.0, 0.0]),
        Candidata("s:2", "Sujeito", "titular de dados", 1, [0.99, 0.01]),
        Candidata("s:3", "Sujeito", "direito de acesso aos dados", 3, [0.0, 1.0]),
        Candidata("s:4", "Sujeito", "acesso aos dados", 2, [0.01, 0.999]),
        Candidata("s:9", "Sujeito", "produto", 2, [0.3, 0.9]),
        Candidata("s:10", "Sujeito", "produtor", 1, [0.3, 0.9]),
        Candidata("s:7", "Sujeito", "segurança pública", 2, [0.7, 0.7]),
        Candidata("s:8", "Sujeito", "segurança do Estado", 1, [0.71, 0.7]),
        Candidata("c:5", "Sujeito", "dado pessoal", 2, [0.5, 0.5]),
        Candidata("c:6", "Sujeito", "dado pessoal sensível", 2, [0.5, 0.5]),
    ]
    grupos = {g.manter: g for g in agrupar(cands, 90, 0.99)}  # fuzzy = 90.9
    assert grupos["s:1"].fundir == ["s:2"] and grupos["s:1"].metodo == "fuzzy"
    assert grupos["s:3"].fundir == ["s:4"] and grupos["s:3"].metodo == "embedding"
    assert "c:5" not in grupos and "c:6" not in grupos
    assert "s:7" not in grupos and "s:8" not in grupos  # embedding sem apoio léxico
    assert "s:9" not in grupos and "s:10" not in grupos  # substituição de termo
