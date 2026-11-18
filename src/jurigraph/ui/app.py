"""Interface em Streamlit com a pergunta, a resposta citada, o subgrafo e a rastreabilidade.

Para rodar use streamlit run src/jurigraph/ui/app.py
"""

import re
from html import escape

import pandas as pd
import streamlit as st
from neo4j_viz import Node, Relationship, VisualizationGraph

from jurigraph import db
from jurigraph.generation.verifier import PESOS
from jurigraph.llm import get_embedder
from jurigraph.rag import Resposta, responder
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

MODOS_UI = {
    "hibrido": ("Híbrido", "Vetor, texto e dois saltos no grafo, mais consulta Cypher gerada e resumos de comunidade."),
    "kag": ("KAG", "Divide a pergunta em passos, resolve cada um no grafo e junta os resultados."),
    "vetorial": ("Só vetorial", "Busca apenas por similaridade de texto, sem usar o grafo. Serve de comparação."),
}

COMPARAR = {"comparar": ("Comparar os 3", "Roda a mesma pergunta nos três modos e mostra lado a lado. "
                                          "Leva uns 20 segundos.")}
ORDEM_COMPARAR = ["vetorial", "hibrido", "kag"]

SUGESTOES = [
    ("Pergunta direta", "Um artigo responde", [
        "O que a LGPD considera dado pessoal sensível?",
        "Por quanto tempo devem ser guardados os registros de conexão à internet?",
    ]),
    ("Várias relações", "Precisa ligar normas no grafo", [
        "Qual tema do STF discute um artigo do Marco Civil, e o que esse artigo exige para "
        "responsabilizar o provedor por conteúdo de terceiros?",
        "Que lei incluiu no CDC o capítulo sobre prevenção do superendividamento?",
    ]),
    ("Visão geral", "Usa os resumos de comunidade", [
        "Como o corpus trata a responsabilidade dos provedores de internet?",
        "Quais órgãos públicos têm atribuições nas normas do corpus?",
    ]),
    ("Fora do corpus", "O sistema deve recusar", [
        "Qual é a pena de reclusão para o crime de furto no Código Penal?",
        "O que o GDPR europeu diz sobre o direito ao esquecimento?",
    ]),
]

CORPUS = [
    ("LGPD", "Lei 13.709/2018"), ("Marco Civil da Internet", "Lei 12.965/2014"),
    ("Código de Defesa do Consumidor", "Lei 8.078/1990"), ("Lei de Acesso à Informação", "Lei 12.527/2011"),
    ("Superendividamento", "Lei 14.181/2021"), ("Regulamento do Marco Civil", "Decreto 8.771/2016"),
    ("Comércio eletrônico", "Decreto 7.962/2013"), ("Temas de repercussão geral", "STF"),
]

ETAPAS = {
    "recuperar": "Buscando trechos e percorrendo o grafo",
    "gerar": "Escrevendo a resposta com citações",
    "verificar": "Conferindo cada frase contra as fontes",
}

CSS = """
<style>
  .block-container {padding-top: 1.2rem; max-width: 1240px;}
  header[data-testid="stHeader"] {height: 0;}
  .topo {display: flex; justify-content: space-between; align-items: flex-end;
         border-bottom: 2px solid #1f4e79; padding-bottom: 10px; margin-bottom: 18px;}
  .topo h1 {font-size: 1.9rem; margin: 0; padding: 0; color: #14213d; letter-spacing: -.01em;}
  .topo .sub {color: #4a5568; font-size: .95rem; margin-top: 2px;}
  .topo .estado {font-size: .85rem; color: #4a5568; text-align: right; line-height: 1.5;}
  .topo .ok {color: #2f7d4f; font-weight: 600;}
  .topo .erro {color: #a5432a; font-weight: 600;}
  .grupo {border-top: 3px solid #1f4e79; padding-top: 6px; margin-bottom: 4px;}
  .grupo.recusa {border-top-color: #b85c1e;}
  .grupo b {font-size: .95rem; color: #14213d;}
  .grupo span {display: block; font-size: .8rem; color: #6b7280;}
  .pergunta-feita {font-size: 1.35rem; font-weight: 600; color: #14213d; margin: 4px 0 6px 0;}
  .meta {font-size: .85rem; color: #4a5568; margin-bottom: 10px;}
  .resposta {font-size: 1.05rem; line-height: 1.65; border-left: 4px solid #1f4e79;
             padding: 12px 18px; background: #f4f6f8; border-radius: 2px; color: #1b1f24;}
  .resposta sup a {text-decoration: none; font-weight: 700; color: #1f4e79;}
  .resposta.recusa {border-left-color: #b85c1e; background: #fbf4ee;}
  .fontes {font-size: .9rem; margin-top: 14px; padding-left: 1.3rem; color: #1b1f24;}
  .fontes li {margin-bottom: 6px;}
  .fontes code {font-size: .72rem; color: #6b7280; background: none;}
  .conf {border: 1px solid #d0d4d9; border-radius: 2px; padding: 14px 16px;}
  .conf .valor {font-size: 2.2rem; font-weight: 700; color: #14213d; line-height: 1;}
  .conf .rot {font-size: .8rem; color: #4a5568; text-transform: uppercase; letter-spacing: .04em;}
  .conf .linha {margin-top: 12px; font-size: .85rem; color: #1b1f24;}
  .conf .linha div.barra {height: 6px; background: #e5e7eb; margin-top: 3px;}
  .conf .linha div.barra i {display: block; height: 6px; background: #1f4e79;}
  .conf table {width: 100%; margin-top: 14px; font-size: .85rem; border-collapse: collapse;}
  .conf td {padding: 3px 0; border-top: 1px solid #eceef1;}
  .conf td:last-child {text-align: right; font-weight: 600;}
  .legenda span {display: inline-block; margin: 0 10px 4px 0; font-size: .85rem;}
  .legenda i {display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 1px;}
  .vazio {color: #4a5568; font-size: .95rem; margin: 6px 0 14px 0;}
</style>
"""


@st.cache_data(ttl=300)
def estatisticas() -> dict[str, int]:
    linha = db.run("""
        CALL () { MATCH (d:Document) RETURN count(d) AS docs }
        CALL () { MATCH (e:Entity) RETURN count(e) AS ents }
        CALL () { MATCH ()-[r]->() RETURN count(r) AS rels }
        RETURN docs, ents, rels""")[0]
    return {"docs": linha["docs"], "ents": linha["ents"], "rels": linha["rels"]}


@st.cache_resource(show_spinner="Preparando o sistema, leva uns 15 segundos na primeira vez...")
def aquecer() -> bool:
    """Carrega uma vez por processo o que a primeira pergunta pagaria (~15 s)."""
    get_embedder().embed_query("aquecimento")
    schema_texto()
    return True


def citados(texto: str) -> list[str]:
    """Ids citados na resposta, na ordem em que aparecem."""
    return list(dict.fromkeys(m.group(2) for m in CITACAO_RE.finditer(texto)))


def descrever(i: str, ctx: Contexto) -> str:
    if i in ctx.trechos:
        t = ctx.trechos[i]
        link = f' · <a href="{escape(t.url)}" target="_blank">fonte</a>' if t.url else ""
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
    """Escolhe os fatos e nós a desenhar, primeiro os citados e depois os mais centrais."""
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


def barra(rotulo: str, valor: float, peso: float) -> str:
    return (f'<div class="linha">{rotulo} <span style="color:#6b7280">peso {peso:.1f}</span>'
            f'<span style="float:right;font-weight:600">{valor:.0%}</span>'
            f'<div class="barra"><i style="width:{max(0.0, min(valor, 1.0)) * 100:.0f}%"></i></div></div>')


def painel_confianca(r: Resposta) -> str:
    v, ctx = r.verificacao, r.contexto
    sustentadas = sum(a.sustentada for a in v.afirmacoes)
    linhas = [
        ("Trechos recuperados", len(ctx.trechos)), ("Fatos do grafo", len(ctx.fatos)),
        ("Entidades", len(ctx.entidades)), ("Consultas Cypher", len(ctx.cyphers)),
        ("Frases mantidas", f"{sustentadas} de {len(v.afirmacoes)}"),
        ("Tempo", f"{r.segundos:.1f} s"), ("Custo", f"US$ {r.tokens['custo_usd']:.4f}"),
    ]
    tabela = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in linhas)
    return (f'<div class="conf"><div class="rot">Confiança</div><div class="valor">{v.confianca:.2f}</div>'
            + barra("Similaridade com a pergunta", v.similaridade, PESOS["similaridade"])
            + barra("Citações que existem no grafo", v.cobertura, PESOS["cobertura"])
            + barra("Frases sustentadas pelas fontes", v.sustentacao, PESOS["sustentacao"])
            + f"<table>{tabela}</table></div>")


def abas(r: Resposta, ids: list[str]) -> None:
    ctx = r.contexto
    t_grafo, t_fontes, t_ver, t_cypher, t_passos, t_nos = st.tabs(
        ["Grafo da resposta", "Trechos de origem", "Verificação", "Consulta Cypher", "Passos", "Entidades"])
    with t_grafo:
        st.caption("Parte do grafo usada nesta resposta. Em laranja, o que foi citado ou faz parte do caminho. "
                   "Tamanho do nó pelo PageRank. Arraste os nós e clique para ver as propriedades.")
        html = grafo_html(ctx, ids)
        st.markdown(legenda(), unsafe_allow_html=True)
        if html:
            st.iframe(html, height=580)
        else:
            st.info("O modo só vetorial não percorre o grafo, por isso não há subgrafo. "
                    "Troque para Híbrido ou KAG para ver as relações.")
    with t_fontes:
        st.caption("Texto original das normas que serviu de contexto, com a similaridade de cosseno com a pergunta.")
        ordem = sorted(ctx.trechos.values(), key=lambda t: (t.id not in ids, -t.score))
        if not ordem:
            st.info("Nenhum trecho recuperado.")
        for t in ordem:
            marca = "Citado · " if t.id in ids else ""
            with st.expander(f"{marca}{t.titulo}, {t.rotulo}  ·  cos {t.score:.2f}", expanded=t.id in ids[:2]):
                st.write(t.texto)
                st.caption(f"id `{t.id}`" + (f" · [abrir no Planalto]({t.url})" if t.url else ""))
    with t_ver:
        st.caption("Cada frase da resposta foi checada contra o contexto. "
                   "Frases sem sustentação ou sem nenhuma citação válida foram retiradas antes de mostrar.")
        if r.verificacao.afirmacoes:
            st.dataframe(pd.DataFrame([{
                "frase": a.texto, "mantida": "sim" if a.sustentada and a.citacoes else "não",
                "citações": ", ".join(a.citacoes), "citações inexistentes": ", ".join(a.citacoes_invalidas),
                "justificativa": a.justificativa} for a in r.verificacao.afirmacoes]),
                hide_index=True, width="stretch")
        else:
            st.info("Não houve frases a verificar porque o sistema não encontrou evidência.")
    with t_cypher:
        st.caption("Consulta gerada a partir da pergunta e do schema real do banco. "
                   "Passou pelo validador, que bloqueia escrita e exige LIMIT, e rodou em sessão só de leitura.")
        if not ctx.cyphers:
            st.info("Nenhuma consulta Cypher gerada neste modo.")
        for q in ctx.cyphers:
            st.code(q, language="cypher")
        if ctx.linhas_cypher:
            st.dataframe(pd.DataFrame([{k: str(v) for k, v in l.items()} for l in ctx.linhas_cypher[:50]]),
                         hide_index=True)
    with t_passos:
        st.caption("Tudo o que o sistema executou para montar o contexto, na ordem.")
        st.dataframe(pd.DataFrame([{"tipo": p.tipo, "descrição": p.descricao, "resultados": p.resultados}
                                   for p in ctx.passos]), hide_index=True, width="stretch")
        for p in ctx.passos:
            if p.tipo in ("plano", "cypher") and p.detalhe:
                st.code(p.detalhe, language="text" if p.tipo == "plano" else "cypher")
    with t_nos:
        st.caption("Entidades do grafo que entraram no contexto, ordenadas pelo PageRank.")
        st.dataframe(pd.DataFrame([{"nome": e.nome, "tipo": e.label, "chave": e.key,
                                    "pagerank": round(e.pagerank, 5), "citada": e.key in ids}
                                   for e in sorted(ctx.entidades.values(), key=lambda e: -e.pagerank)]),
                     hide_index=True, width="stretch")


def cabecalho() -> None:
    try:
        e = estatisticas()
        estado = (f'<span class="ok">● Neo4j conectado</span><br>{e["docs"]} documentos · '
                  f'{e["ents"]:,} entidades · {e["rels"]:,} relações'.replace(",", "."))
    except Exception:  # sem banco a tela avisa em vez de quebrar
        estado = '<span class="erro">● Neo4j fora do ar</span><br>rode docker compose up -d neo4j'
    st.markdown(f'<div class="topo"><div><h1>JuriGraph</h1><div class="sub">Pesquisa em legislação '
                f'brasileira com grafo de conhecimento e respostas citadas</div></div>'
                f'<div class="estado">{estado}</div></div>', unsafe_allow_html=True)


def barra_lateral() -> None:
    with st.sidebar:
        st.markdown("**Histórico**")
        hist: list = st.session_state.setdefault("historico", [])
        if not hist:
            st.caption("As perguntas feitas aparecem aqui e reabrem sem gastar de novo.")
        for k in range(len(hist) - 1, -1, -1):
            h = hist[k]
            base = h[0] if isinstance(h, list) else h
            rotulo = (base.pergunta[:54] + "…") if len(base.pergunta) > 54 else base.pergunta
            if isinstance(h, list):
                rotulo, dica = f"3 modos · {rotulo}", "Comparação dos três modos"
            else:
                dica = f"{MODOS_UI[h.modo][0]} · {h.segundos:.1f} s"
            tipo = "primary" if st.session_state.get("atual") == k else "tertiary"
            if st.button(rotulo, key=f"h{k}", help=dica, type=tipo, width="stretch"):
                st.session_state["atual"] = k
                st.rerun()
        if hist and st.button("Limpar histórico", type="secondary"):
            st.session_state["historico"], st.session_state["atual"] = [], None
            st.rerun()
        st.divider()
        st.markdown("**O que está no corpus**")
        st.markdown("\n".join(f"- {n} <span style='color:#6b7280'>({ref})</span>" for n, ref in CORPUS),
                    unsafe_allow_html=True)
        st.caption("Perguntas fora dessas normas são recusadas. Ferramenta de pesquisa, "
                   "não substitui orientação jurídica.")


def sugestoes() -> None:
    cols = st.columns(len(SUGESTOES))
    for c, (titulo, sub, perguntas) in zip(cols, SUGESTOES):
        with c:
            classe = "grupo recusa" if titulo == "Fora do corpus" else "grupo"
            st.markdown(f'<div class="{classe}"><b>{titulo}</b><span>{sub}</span></div>', unsafe_allow_html=True)
            for q in perguntas:
                if st.button(q, key=f"s-{q}", type="tertiary"):
                    st.session_state["executar"] = q
                    st.rerun()


def pesquisar(pergunta: str, modo: str) -> None:
    modos = ORDEM_COMPARAR if modo == "comparar" else [modo]
    respostas: list[Resposta] = []
    with st.status("Pesquisando...", expanded=True) as status:
        for n, m in enumerate(modos, 1):
            prefixo = f"{n}/{len(modos)} {MODOS_UI[m][0]} · " if len(modos) > 1 else ""

            def etapa(nome: str, prefixo: str = prefixo) -> None:
                status.update(label=prefixo + ETAPAS[nome] + "...")
                st.write(prefixo + ETAPAS[nome])
            try:
                respostas.append(responder(pergunta, m, etapa=etapa))
            except Exception as exc:  # erro de rede ou do banco aparece na tela sem derrubar a sessão
                status.update(label="Não foi possível responder", state="error")
                st.error(f"Algo falhou ao pesquisar. Confira se o Neo4j está no ar e a chave no .env. "
                         f"Detalhe {exc}")
                return
        total = sum(r.segundos for r in respostas)
        status.update(label=f"Pronto em {total:.1f} s", state="complete", expanded=False)
    hist = st.session_state.setdefault("historico", [])
    hist.append(respostas if len(respostas) > 1 else respostas[0])
    st.session_state["atual"] = len(hist) - 1


def explicar_recusa(r: Resposta) -> None:
    """Mostra por que não houve resposta e os trechos mais parecidos, para o usuário reformular."""
    motivos = [re.sub(r"\s*\[[nr]:[^\]]+\]", "", a.texto).strip() for a in r.bruta.afirmacoes]
    if motivos:
        st.markdown("**Por que não respondeu**")
        st.markdown(" ".join(escape(m) for m in motivos if m))
    proximos = sorted(r.contexto.trechos.values(), key=lambda t: -t.score)[:3]
    if proximos:
        st.markdown("**Trechos mais próximos que o sistema encontrou**")
        for t in proximos:
            with st.expander(f"{t.titulo}, {t.rotulo}  ·  cos {t.score:.2f}"):
                st.write(t.texto)
    st.caption("O sistema prefere não responder a inventar. Tente outro modo ou uma pergunta mais específica.")


def mostrar(r: Resposta) -> None:
    html, ids = resposta_html(r)
    st.markdown(f'<div class="pergunta-feita">{escape(r.pergunta)}</div>', unsafe_allow_html=True)
    if r.verificacao.recusou:
        st.badge("Sem evidência no corpus, o sistema não respondeu", color="orange")
    else:
        st.badge(f"Respondida com {len(ids)} fonte" + ("s" if len(ids) != 1 else ""), color="green")
    esq, dir_ = st.columns([2.2, 1], gap="large")
    with esq:
        st.markdown(f'<div class="meta">Modo {MODOS_UI[r.modo][0]}</div>' + html, unsafe_allow_html=True)
        if r.verificacao.recusou:
            explicar_recusa(r)
        if ids:
            refs = "".join(f'<li id="ref-{k + 1}">{descrever(i, r.contexto)} <code>{escape(i)}</code></li>'
                           for k, i in enumerate(ids))
            st.markdown(f"<ol class='fontes'>{refs}</ol>", unsafe_allow_html=True)
    with dir_:
        st.markdown(painel_confianca(r), unsafe_allow_html=True)
    st.write("")
    abas(r, ids)


def comparar(rs: list[Resposta]) -> None:
    st.markdown(f'<div class="pergunta-feita">{escape(rs[0].pergunta)}</div>', unsafe_allow_html=True)
    st.markdown('<div class="meta">A mesma pergunta nos três modos. Gerador e verificador são os mesmos, '
                'só muda a forma de buscar o contexto.</div>', unsafe_allow_html=True)
    cols = st.columns(len(rs), gap="medium")
    for c, r in zip(cols, rs):
        html, ids = resposta_html(r)
        with c:
            st.markdown(f"**{MODOS_UI[r.modo][0]}**")
            if r.verificacao.recusou:
                st.badge("Não respondeu", color="orange")
            else:
                st.badge(f"{len(ids)} fonte" + ("s" if len(ids) != 1 else ""), color="green")
            st.markdown(html, unsafe_allow_html=True)
            if ids:
                refs = "".join(f"<li>{descrever(i, r.contexto)}</li>" for i in ids)
                st.markdown(f"<ol class='fontes'>{refs}</ol>", unsafe_allow_html=True)
    st.write("")
    st.markdown("**Comparação**")
    metricas = {
        "Respondeu": lambda r: "não" if r.verificacao.recusou else "sim",
        "Confiança": lambda r: f"{r.verificacao.confianca:.2f}",
        "Fontes citadas": lambda r: len(citados(r.texto)),
        "Trechos recuperados": lambda r: len(r.contexto.trechos),
        "Fatos do grafo": lambda r: len(r.contexto.fatos),
        "Consultas Cypher": lambda r: len(r.contexto.cyphers),
        "Frases cortadas pelo verificador": lambda r: sum(
            not (a.sustentada and a.citacoes) for a in r.verificacao.afirmacoes),
        "Tempo": lambda r: f"{r.segundos:.1f} s",
        "Custo": lambda r: f"US$ {r.tokens['custo_usd']:.4f}",
    }
    st.dataframe(pd.DataFrame([{"": nome, **{MODOS_UI[r.modo][0]: str(f(r)) for r in rs}}
                               for nome, f in metricas.items()]), hide_index=True, width="stretch")
    st.markdown("**Detalhes de um modo**")
    escolha = st.segmented_control("Ver o rastro de", [r.modo for r in rs], default=rs[1].modo,
                                   format_func=lambda m: MODOS_UI[m][0], key="det_modo",
                                   label_visibility="collapsed") or rs[1].modo
    r = next(x for x in rs if x.modo == escolha)
    abas(r, citados(r.texto))


def main() -> None:
    st.set_page_config(page_title="JuriGraph", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    cabecalho()
    barra_lateral()
    aquecer()

    pendente = st.session_state.pop("executar", None)
    if pendente:
        st.session_state["pergunta_txt"] = pendente
    opcoes = {**{m: v for m, v in MODOS_UI.items()}, **COMPARAR}
    modo = st.segmented_control("Modo de busca", list(opcoes), format_func=lambda m: opcoes[m][0],
                                default="hibrido", key="modo") or "hibrido"
    st.caption(opcoes[modo][1])
    with st.form("form", border=False, enter_to_submit=False):
        texto = st.text_area("Sua pergunta", key="pergunta_txt", height=90,
                             placeholder="Pergunte qualquer coisa sobre LGPD, Marco Civil, CDC, LAI ou "
                                         "superendividamento. Ex.: o titular pode pedir a exclusão dos seus dados?")
        enviar = st.form_submit_button("Comparar" if modo == "comparar" else "Pesquisar", type="primary")
    if enviar and texto.strip():
        pendente = texto.strip()

    hist: list = st.session_state.setdefault("historico", [])
    if pendente:
        pesquisar(pendente, modo)
    atual = st.session_state.get("atual")
    if atual is None or atual >= len(hist):
        st.markdown('<div class="vazio">Escreva a sua pergunta acima ou comece por um destes exemplos.</div>',
                    unsafe_allow_html=True)
        sugestoes()
        return
    with st.expander("Mais exemplos de perguntas"):
        sugestoes()
    if isinstance(hist[atual], list):
        comparar(hist[atual])
    else:
        mostrar(hist[atual])


main()
