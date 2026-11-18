"""Regras do verificador que não dependem de rede."""

from jurigraph.generation import verifier
from jurigraph.generation.answer import Afirmacao, RespostaLLM, normalizar_id
from jurigraph.retrieval.context import Contexto, Fato, TrechoCtx


def test_normaliza_ids_de_trecho_e_relacao():
    assert normalizar_id("[n:mci-03-cap-iii:004]") == "mci-03-cap-iii:004"
    assert normalizar_id("r:r-fedbf806b5") == "r-fedbf806b5"
    assert normalizar_id("r:fedbf806b5") == "r-fedbf806b5"


def _ctx() -> Contexto:
    ctx = Contexto()
    ctx.trechos["mci:004"] = TrechoCtx("mci:004", "mci", "Marco Civil", "Art. 13", "prazo de 1 ano", "", 0.8)
    ctx.fatos["r-abc"] = Fato("r-abc", "lei:12965", "CONTEM", "artigo:12965:13")
    return ctx


def _sem_juiz(afs, ctx):
    for a in afs:
        a.sustentada = True


def test_relacao_sem_prefixo_conta_como_valida(monkeypatch):
    monkeypatch.setattr(verifier, "_julgar", _sem_juiz)
    r = RespostaLLM(suficiente=True, afirmacoes=[
        Afirmacao(texto="Guarda por 1 ano.", citacoes=["n:mci:004", "r:abc"])])
    v = verifier.verificar(r, _ctx())
    assert not v.recusou
    assert v.afirmacoes[0].citacoes_invalidas == []


def test_citacao_inexistente_nao_derruba_frase_com_fonte_valida(monkeypatch):
    monkeypatch.setattr(verifier, "_julgar", _sem_juiz)
    r = RespostaLLM(suficiente=True, afirmacoes=[
        Afirmacao(texto="Guarda por 1 ano.", citacoes=["n:mci:004", "n:nao-existe"])])
    v = verifier.verificar(r, _ctx())
    assert not v.recusou
    assert "nao-existe" not in v.resposta_final
    assert v.cobertura == 0.5


def test_frase_so_com_citacao_inexistente_sai(monkeypatch):
    monkeypatch.setattr(verifier, "_julgar", _sem_juiz)
    r = RespostaLLM(suficiente=True, afirmacoes=[
        Afirmacao(texto="Inventada.", citacoes=["n:nao-existe"])])
    assert verifier.verificar(r, _ctx()).recusou
