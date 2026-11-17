"""Interface Streamlit: pergunta, resposta citada, subgrafo e rastreabilidade.

Rodar: streamlit run src/jurigraph/ui/app.py
"""

import json
import re
from html import escape

import pandas as pd
import streamlit as st
from neo4j_viz import Node, Relationship, VisualizationGraph

from jurigraph import db
from jurigraph.config import ROOT
from jurigraph.generation.verifier import PESOS
from jurigraph.llm import get_embedder
from jurigraph.rag import MODOS, Resposta, responder
from jurigraph.retrieval.context import Contexto
from jurigraph.retrieval.text2cypher import schema_texto

CORES = {
    "Lei": "#1f4e79", "Artigo": "#2e75b6", "Precedente": "#7030a0", "Tribunal": "#4b2a63",
    "Orgao": "#c55a11", "Conceito": "#548235", "Sujeito": "#a07800", "Direito": "#1f7f74",
    "Obrigacao": "#a5432a", "Sancao": "#c00000", "Community": "#595959", "Entity": "#7f7f7f",
}
COR_DESTAQUE = "#e8a33d"
CITACAO_RE = re.compile(r"\[(n|r):([^\]]+)\]")
MAX_NOS = 70

CSS = """
<style>
  .block-container {padding-top: 1.6rem; max-width: 1200px;}
  div[data-testid="stMetric"] {border: 1px solid #d0d4d9; border-radius: 3px; padding: 6px 10px;}
  .resposta {font-size: 1.05rem; line-height: 1.6; border-left: 3px solid #1f4e79;
             padding: 6px 14px; background: #f4f6f8; border-radius: 2px; color: #1b1f24;}
  .resposta sup a {text-decoration: none; font-weight: 600; color: #1f4e79;}
  .recusa {border-left-color: #a5432a;}
  .legenda span {display: inline-block; margin: 0 10px 4px 0; font-size: .85rem;}
  .legenda i {display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 1px;}
</style>
"""


@st.cache_data(ttl=300)
def estatisticas() -> dict[str, int]:
    r = db.run("MATCH (n) RETURN count(n) AS nos")[0]["nos"]
    e = db.run("MATCH (n:Entity) RETURN count(n) AS n")[0]["n"]
    rel = db.run("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    d = db.run("MATCH (d:Document) RETURN count(d) AS n")[0]["n"]
    return {"Documentos": d, "Nós": r, "Entidades": e, "Relações": rel}


@st.cache_resource(show_spinner="Carregando o modelo de embeddings e o schema do grafo...")
def aquecer() -> bool:
    """Carrega uma vez por processo o que a primeira pergunta pagaria (~15 s)."""
    get_embedder().embed_query("aquecimento")
    schema_texto()
    return True


@st.cache_data
def exemplos() -> list[str]:
    arq = ROOT / "data" / "eval" / "perguntas.jsonl"
    return [json.loads(l)["pergunta"] for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]


def citados(texto: str) -> list[str]:
    """Ids citados na resposta, na ordem em que aparecem."""
    return list(dict.fromkeys(m.group(2) for m in CITACAO_RE.finditer(texto)))


def descrever(i: str, ctx: Contexto) -> str:
    if i in ctx.trechos:
        t = ctx.trechos[i]
        link = f' — <a href="{escape(t.url)}" target="_blank">fonte</a>' if t.url else ""
        return f"<b>{escape(t.titulo)}</b>, {escape(t.rotulo)}{link}"
    if i in ctx.fatos:
        f = ctx.fatos[i]
        return f"Fato: {escape(ctx.nome(f.origem))} <code>{f.tipo}</code> {escape(ctx.nome(f.destino))}"
    if i in ctx.entidades:
        e = ctx.entidades[i]
        return f"Entidade ({e.label}): {escape(e.nome)}"
    if i in ctx.resumos:
        return f"Resumo de comunidade: {escape(ctx.resumos[i][:160])}…"
    return escape(i)


def resposta_html(r: Resposta) -> tuple[str, list[str]]:
    ids = citados(r.texto)
    numero = {i: k + 1 for k, i in enumerate(ids)}
    corpo = CITACAO_RE.sub(lambda m: f'<sup><a href="#ref-{numero[m.group(2)]}">[{numero[m.group(2)]}]</a></sup>',
                           escape(r.texto).replace("&#x27;", "'"))
    classe = "resposta recusa" if r.verificacao.recusou else "resposta"
    return f'<div class="{classe}">{corpo}</div>', ids


def _subgrafo(ctx: Contexto, destaque: set[str]) -> tuple[list[str], list[str]]:
    """Fatos e nós a desenhar: citados, caminho e vizinhança mais central, até MAX_NOS."""
    fatos = sorted(ctx.fatos.values(), key=lambda f: (
        not ({f.id, f.origem, f.destino} & destaque), f.salto,
        -(ctx.entidades.get(f.destino).pagerank if f.destino in ctx.entidades else 0)))
    nos: list[str] = [k for k in destaque if k in ctx.entidades]
    escolhidos = []
    for f in fatos:
        novos = [k for k in (f.origem, f.destino) if k not in nos]
        if len(nos) + len(novos) > MAX_NOS:
            continue
        nos += novos
        escolhidos.append(f.id)
    return nos, escolhidos


def grafo_html(ctx: Contexto, ids_citados: list[str]) -> str:
    no_caminho = {x for c in ctx.caminhos for x in c}
    destaque = set(ids_citados) | no_caminho
    for i in ids_citados:  # um chunk citado destaca as pontas dos fatos que vieram dele
        destaque |= {k for f in ctx.fatos.values() if i in f.fontes for k in (f.origem, f.destino)}
    nos, fatos = _subgrafo(ctx, destaque)
    if not nos:
        return ""
    prs = [ctx.entidades[k].pagerank for k in nos if k in ctx.entidades] or [0.0]
    topo = max(prs) or 1.0
    vnos = []
    for k in nos:
        e = ctx.entidades.get(k)
        if e is None:
            continue
        vnos.append(Node(id=k, caption=e.nome[:40], size=12 + 28 * (e.pagerank / topo),
                         color=COR_DESTAQUE if k in destaque else CORES.get(e.label, CORES["Entity"]),
                         properties={"tipo": e.label, "chave": k, "pagerank": round(e.pagerank, 4),
                                     "descricao": e.descricao}))
    vrels = []
    for fid in fatos:
        f = ctx.fatos[fid]
        vrels.append(Relationship(id=fid, source=f.origem, target=f.destino, caption=f.tipo,
                                  color=COR_DESTAQUE if fid in destaque else "#9aa3ad",
                                  width=4 if fid in destaque else 1,
                                  properties={"id": fid, "evidencia": f.evidencia, "salto": f.salto}))
    return VisualizationGraph(nodes=vnos, relationships=vrels).render(
        height="560px", theme="light", show_search_button=True).data


def legenda() -> str:
    itens = "".join(f'<span><i style="background:{c}"></i>{l}</span>'
                    for l, c in CORES.items() if l not in ("Entity", "Community"))
    return f'<div class="legenda">{itens}<span><i style="background:{COR_DESTAQUE}"></i>citado / caminho</span></div>'


def painel_confianca(r: Resposta) -> None:
    v = r.verificacao
    c = st.columns(5)
    c[0].metric("Confiança", f"{v.confianca:.2f}")
    c[1].metric(f"Similaridade (×{PESOS['similaridade']})", f"{v.similaridade:.2f}")
    c[2].metric(f"Citações válidas (×{PESOS['cobertura']})", f"{v.cobertura:.0%}")
    c[3].metric(f"Sustentadas (×{PESOS['sustentacao']})", f"{v.sustentacao:.0%}")
    c[4].metric("Tempo / custo", f"{r.segundos:.1f}s", f"US$ {r.tokens['custo_usd']:.4f}", delta_color="off")


def abas(r: Resposta, ids: list[str]) -> None:
    ctx = r.contexto
    t_grafo, t_fontes, t_cypher, t_passos, t_ver, t_nos = st.tabs(
        ["Subgrafo", "Trechos de origem", "Cypher", "Passos", "Verificação", "Nós consultados"])
    with t_grafo:
        html = grafo_html(ctx, ids)
        st.markdown(legenda(), unsafe_allow_html=True)
        if html:
            st.iframe(html, height=580)
            st.caption("Tamanho do nó = PageRank. Clique num nó ou relação para ver as propriedades.")
        else:
            st.info("Este modo não recupera fatos do grafo (só trechos).")
    with t_fontes:
        ordem = sorted(ctx.trechos.values(), key=lambda t: (t.id not in ids, -t.score))
        for t in ordem:
            marca = "citado · " if t.id in ids else ""
            with st.expander(f"{marca}{t.titulo} — {t.rotulo}  (cos {t.score:.2f})", expanded=t.id in ids[:2]):
                st.write(t.texto)
                st.caption(f"id `{t.id}` · {t.url}")
    with t_cypher:
        if not ctx.cyphers:
            st.info("Nenhuma consulta Cypher gerada neste modo.")
        for q in ctx.cyphers:
            st.code(q, language="cypher")
        if ctx.linhas_cypher:
            st.dataframe(pd.DataFrame([{k: str(v) for k, v in l.items()} for l in ctx.linhas_cypher[:50]]),
                         hide_index=True)
    with t_passos:
        st.dataframe(pd.DataFrame([{"tipo": p.tipo, "descrição": p.descricao, "resultados": p.resultados}
                                   for p in ctx.passos]), hide_index=True, width="stretch")
        for p in ctx.passos:
            if p.tipo in ("plano", "cypher") and p.detalhe:
                st.code(p.detalhe, language="text" if p.tipo == "plano" else "cypher")
    with t_ver:
        st.dataframe(pd.DataFrame([{
            "afirmação": a.texto, "sustentada": "sim" if a.sustentada else "não",
            "citações": ", ".join(a.citacoes), "ids inexistentes": ", ".join(a.citacoes_invalidas),
            "justificativa do verificador": a.justificativa} for a in r.verificacao.afirmacoes]),
            hide_index=True, width="stretch")
        st.caption("Afirmações não sustentadas ou com ids inexistentes são removidas da resposta final.")
    with t_nos:
        st.dataframe(pd.DataFrame([{"chave": e.key, "nome": e.nome, "tipo": e.label,
                                    "pagerank": round(e.pagerank, 5), "citado": e.key in ids}
                                   for e in sorted(ctx.entidades.values(), key=lambda e: -e.pagerank)]),
                     hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title="JuriGraph", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.header("JuriGraph")
        st.caption("Pesquisa jurídica com GraphRAG e KAG sobre Neo4j")
        modo = st.radio("Modo de recuperação", list(MODOS), format_func=lambda m: MODOS[m], index=1)
        st.divider()
        try:
            st.dataframe(pd.DataFrame(estatisticas().items(), columns=["", "total"]), hide_index=True)
        except Exception as exc:  # banco fora do ar: a UI avisa em vez de quebrar
            st.error(f"Neo4j indisponível: {exc}")
        st.caption("Corpus: LGPD, Marco Civil, CDC, LAI, Lei 14.181, Decretos 8.771 e 7.962, temas do STF. "
                   "Pesquisa, não aconselhamento jurídico.")
    aquecer()
    st.subheader("Pergunte sobre a legislação do corpus")
    exemplo = st.selectbox("Exemplos", [""] + exemplos(), index=0)
    pergunta = st.text_area("Pergunta", value=exemplo, height=80)
    if st.button("Perguntar", type="primary", disabled=not pergunta.strip()):
        with st.spinner("Recuperando, gerando e verificando..."):
            st.session_state["resposta"] = responder(pergunta.strip(), modo)
    r: Resposta | None = st.session_state.get("resposta")
    if r is None:
        return
    st.caption(f"Modo: {MODOS[r.modo]}")
    html, ids = resposta_html(r)
    st.markdown(html, unsafe_allow_html=True)
    if ids:
        refs = "".join(f'<li id="ref-{k + 1}">{descrever(i, r.contexto)} <code>{escape(i)}</code></li>'
                       for k, i in enumerate(ids))
        st.markdown(f"<ol style='font-size:.9rem'>{refs}</ol>", unsafe_allow_html=True)
    painel_confianca(r)
    abas(r, ids)


main()
