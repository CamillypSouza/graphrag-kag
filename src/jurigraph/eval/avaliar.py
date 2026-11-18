"""Avaliação comparativa entre RAG vetorial, GraphRAG híbrido e GraphRAG com planejador KAG.

Métricas calculadas em cada modo
- acerto, o juiz LLM compara a resposta com a esperada (correta 1, parcial 0,5).
  Nas perguntas impossíveis o acerto é recusar.
- alucinação bruta, porcentagem de afirmações que o verificador não sustentou.
- impossíveis respondidas, perguntas sem resposta no corpus em que o sistema não recusou.
- fidelidade das citações, afirmações cujas citações existem no subgrafo recuperado.
- latência e custo por pergunta (o juiz da avaliação não entra no custo).
"""

import argparse
import json
import logging
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Literal

from neo4j_graphrag.types import LLMMessage
from pydantic import Field

from jurigraph import db
from jurigraph.config import ROOT, get_settings
from jurigraph.llm import Estrito, make_llm
from jurigraph.rag import MODOS, responder

log = logging.getLogger(__name__)
TIPOS = {"um_salto": "Um salto", "multi_hop": "Multi-hop", "global": "Global", "impossivel": "Impossível"}


class Nota(Estrito):
    veredito: Literal["correta", "parcial", "incorreta"]
    motivo: str = Field(description="uma frase")


JUIZ = """Compare a RESPOSTA DO SISTEMA com a RESPOSTA ESPERADA para a pergunta.
correta = traz a informação essencial da esperada, sem contradizê-la;
parcial = acerta parte do essencial ou é vaga; incorreta = erra, contradiz ou se recusa.
Ignore as marcas de citação [n:...] e [r:...].

PERGUNTA: {pergunta}
RESPOSTA ESPERADA: {esperada}
RESPOSTA DO SISTEMA: {obtida}"""


@dataclass
class Resultado:
    id: str
    tipo: str
    modo: str
    pergunta: str
    resposta: str
    recusou: bool
    acerto: float
    veredito: str
    motivo: str
    chaves_ok: bool
    afirmacoes: int
    nao_sustentadas: int
    citacoes_validas: float
    confianca: float
    segundos: float
    custo_usd: float
    tokens: int
    cypher: list[str]


def _chaves(resposta: str, chaves: list[str]) -> bool:
    """Cada chave (com alternativas separadas por |) aparece na resposta."""
    baixo = resposta.lower()
    return all(any(alt.lower() in baixo for alt in ch.split("|")) for ch in chaves)


def _julgar(p: dict, resposta: str, recusou: bool) -> tuple[float, str, str]:
    if p["tipo"] == "impossivel":
        return (1.0, "correta", "recusou") if recusou else (0.0, "incorreta", "respondeu sem evidência")
    if recusou:
        return 0.0, "incorreta", "recusou uma pergunta respondível"
    prompt = JUIZ.format(pergunta=p["pergunta"], esperada=p["resposta_esperada"], obtida=resposta)
    nota = Nota.model_validate_json(
        make_llm().invoke([LLMMessage(role="user", content=prompt)], response_format=Nota).content)
    return {"correta": 1.0, "parcial": 0.5, "incorreta": 0.0}[nota.veredito], nota.veredito, nota.motivo


def avaliar_um(p: dict, modo: str) -> Resultado:
    r = responder(p["pergunta"], modo)  # type: ignore[arg-type]
    v = r.verificacao
    acerto, veredito, motivo = _julgar(p, r.texto, v.recusou)
    afs = v.afirmacoes
    return Resultado(
        id=p["id"], tipo=p["tipo"], modo=modo, pergunta=p["pergunta"], resposta=r.texto,
        recusou=v.recusou, acerto=acerto, veredito=veredito, motivo=motivo,
        chaves_ok=_chaves(r.texto, p["chaves"]) if p["chaves"] else v.recusou,
        afirmacoes=len(afs), nao_sustentadas=sum(not a.sustentada for a in afs),
        citacoes_validas=v.cobertura,
        confianca=v.confianca, segundos=r.segundos, custo_usd=r.tokens["custo_usd"],
        tokens=int(r.tokens["tokens_entrada"] + r.tokens["tokens_saida"]), cypher=r.contexto.cyphers)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _metricas(rs: list[Resultado]) -> dict[str, str]:
    respondiveis = [r for r in rs if r.tipo != "impossivel"]
    impossiveis = [r for r in rs if r.tipo == "impossivel"]
    afs = sum(r.afirmacoes for r in rs)
    lat = sorted(r.segundos for r in rs)
    com_afs = [r for r in rs if r.afirmacoes]
    return {
        "Acerto (respondíveis)": _pct(statistics.mean(r.acerto for r in respondiveis)) if respondiveis else "-",
        "Acerto (impossíveis = recusa)": _pct(statistics.mean(r.acerto for r in impossiveis)) if impossiveis else "-",
        "Palavras-chave presentes": _pct(statistics.mean(r.chaves_ok for r in respondiveis)) if respondiveis else "-",
        "Alucinação bruta (afirmações não sustentadas)": _pct(sum(r.nao_sustentadas for r in rs) / afs) if afs else "-",
        "Impossíveis respondidas": _pct(statistics.mean(not r.recusou for r in impossiveis)) if impossiveis else "-",
        "Fidelidade das citações": _pct(statistics.mean(r.citacoes_validas for r in com_afs)) if com_afs else "-",
        "Recusas em respondíveis": _pct(statistics.mean(r.recusou for r in respondiveis)) if respondiveis else "-",
        "Latência média (s)": f"{statistics.mean(lat):.1f}",
        "Latência p95 (s)": f"{lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)]:.1f}",
        "Custo total (US$)": f"{sum(r.custo_usd for r in rs):.3f}",
        "Custo médio por pergunta (US$)": f"{statistics.mean(r.custo_usd for r in rs):.4f}",
    }


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
    out = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    return "\n".join(out + ["| " + " | ".join(l) + " |" for l in linhas])


def relatorio(rs: list[Resultado], n_perguntas: int) -> str:
    modos = [m for m in MODOS if any(r.modo == m for r in rs)]
    por_modo = {m: _metricas([r for r in rs if r.modo == m]) for m in modos}
    nomes = list(next(iter(por_modo.values())))
    geral = _tabela(["Métrica"] + [MODOS[m] for m in modos],
                    [[n] + [por_modo[m][n] for m in modos] for n in nomes])
    por_tipo = _tabela(["Tipo de pergunta"] + [MODOS[m] for m in modos], [
        [TIPOS[t]] + [_pct(statistics.mean(r.acerto for r in rs if r.modo == m and r.tipo == t))
                      for m in modos]
        for t in TIPOS if any(r.tipo == t for r in rs)])
    s = get_settings()
    return f"""# Avaliação

Gerado por `python -m jurigraph.eval.avaliar` em {time.strftime('%d/%m/%Y %H:%M')}.
Perguntas: {n_perguntas} (`data/eval/perguntas.jsonl`). Modelo: `{s.llm_model}`. Embeddings: `{s.embedding_model}`.
Resultados por pergunta: `data/eval/resultados.jsonl`.

Os três modos usam o mesmo gerador e o mesmo verificador; só a recuperação muda.
O custo usa o preço configurado (US$ {s.llm_price_input_per_m}/{s.llm_price_output_per_m} por 1M tokens de
entrada/saída) e não inclui o juiz da avaliação.

## Resultado geral

{geral}

## Acerto por tipo de pergunta

{por_tipo}

## Como ler

- **Acerto:** veredito de um juiz LLM contra a resposta esperada (correta = 1, parcial = 0,5). Nas
  perguntas impossíveis, acerto significa recusar ("não há evidência no grafo").
- **Alucinação bruta:** afirmações que o gerador produziu e o verificador não conseguiu sustentar no
  contexto. Elas são removidas antes da resposta final; o número mede o quanto o verificador precisou agir.
- **Impossíveis respondidas:** a falha mais grave, uma resposta dada sem base no corpus.
- **Fidelidade das citações:** fração das citações que apontam para ids presentes no subgrafo recuperado.
- **Limitações:** o juiz é o mesmo modelo que gera as respostas, e o conjunto de perguntas é pequeno e foi
  escrito pela equipe a partir do próprio corpus.
- **Análise dos resultados:** `docs/artigo/discussao.tex`.
"""


LATEX_LINHAS = ["Acerto (respondíveis)", "Acerto (impossíveis = recusa)", "Alucinação bruta (afirmações não sustentadas)",
                "Impossíveis respondidas", "Fidelidade das citações", "Latência média (s)",
                "Custo médio por pergunta (US$)"]
LATEX_MODOS = {"vetorial": "Vetorial", "hibrido": "Híbrido", "kag": "KAG"}


def _esc(t: str) -> str:
    return t.replace("%", "\\%").replace("$", "\\$")


def tabela_latex(rs: list[Resultado]) -> str:
    """Gera as tabelas do artigo direto dos resultados."""
    modos = [m for m in MODOS if any(r.modo == m for r in rs)]
    met = {m: _metricas([r for r in rs if r.modo == m]) for m in modos}
    cab = " & ".join(["Métrica"] + [LATEX_MODOS[m] for m in modos])
    linhas = [" & ".join([_esc(n)] + [_esc(met[m][n]) for m in modos]) + " \\\\" for n in LATEX_LINHAS]
    tipos = [" & ".join([TIPOS[t]] + [_esc(_pct(statistics.mean(r.acerto for r in rs if r.modo == m and r.tipo == t)))
                                      for m in modos]) + " \\\\" for t in TIPOS if any(r.tipo == t for r in rs)]
    cols = "l" + "r" * len(modos)
    return "\n".join([
        "% Gerado por python -m jurigraph.eval.avaliar; não editar à mão.",
        "\\begin{table}[ht]\\centering\\small",
        f"\\caption{{Resultados gerais ({len({r.id for r in rs})} perguntas por modo).}}\\label{{tab:geral}}",
        f"\\begin{{tabular}}{{{cols}}}\\hline", cab + " \\\\ \\hline", *linhas, "\\hline\\end{tabular}\\end{table}",
        "\\begin{table}[ht]\\centering\\small",
        "\\caption{Acerto por tipo de pergunta.}\\label{tab:tipos}",
        f"\\begin{{tabular}}{{{cols}}}\\hline", cab.replace("Métrica", "Tipo") + " \\\\ \\hline", *tipos,
        "\\hline\\end{tabular}\\end{table}", ""])


def gravar_saidas(resultados: list[Resultado], n_perguntas: int) -> str:
    texto = relatorio(resultados, n_perguntas)
    (ROOT / "docs" / "avaliacao.md").write_text(texto, encoding="utf-8")
    (ROOT / "docs" / "artigo" / "resultados.tex").write_text(tabela_latex(resultados), encoding="utf-8")
    return texto


def main() -> None:
    ap = argparse.ArgumentParser(description="Avaliação dos três modos")
    ap.add_argument("--modos", default="vetorial,hibrido,kag")
    ap.add_argument("--limite", type=int, help="só as N primeiras perguntas")
    ap.add_argument("--so-relatorio", action="store_true", help="regera os relatórios de resultados.jsonl")
    a = ap.parse_args()
    saida = ROOT / "data" / "eval" / "resultados.jsonl"
    if a.so_relatorio:
        rs = [Resultado(**json.loads(l)) for l in saida.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(gravar_saidas(rs, len({r.id for r in rs})))
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for ruidoso in ("neo4j", "httpx", "httpx2", "sentence_transformers", "neo4j_graphrag"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    caminho = ROOT / "data" / "eval" / "perguntas.jsonl"
    perguntas = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    perguntas = perguntas[: a.limite]
    resultados: list[Resultado] = []
    for modo in a.modos.split(","):
        for p in perguntas:
            try:
                r = avaliar_um(p, modo)
            except Exception as exc:  # registra o erro e continua, a falha conta contra o modo
                log.warning("%s/%s falhou: %s", modo, p["id"], exc)
                r = Resultado(p["id"], p["tipo"], modo, p["pergunta"], f"ERRO: {exc}", True, 0.0,
                              "incorreta", "erro de execução", False, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, [])
            resultados.append(r)
            log.info("%-8s %s %-9s acerto=%.1f conf=%.2f %.1fs", modo, p["id"], r.veredito, r.acerto,
                     r.confianca, r.segundos)
    saida.write_text("\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in resultados) + "\n",
                     encoding="utf-8")
    print(gravar_saidas(resultados, len(perguntas)))
    db.close_driver()


if __name__ == "__main__":
    main()
