"""Gravação no Neo4j com MERGE em lotes, sem duplicar ao rodar de novo."""

from dataclasses import asdict

from jurigraph import db
from jurigraph.ingestion.records import Documento, Extracao, Trecho
from jurigraph.llm import embed_batch

LOTE = 500


def _lotes(itens: list[dict], tamanho: int = LOTE) -> list[list[dict]]:
    return [itens[i: i + tamanho] for i in range(0, len(itens), tamanho)]


def apagar_trechos(doc_id: str) -> None:
    """Remove os chunks de um documento que mudou (as entidades ficam)."""
    db.run("MATCH (:Document {id: $id})<-[:PARTE_DE]-(c:Chunk) DETACH DELETE c", id=doc_id)


def gravar_documento(doc: Documento, trechos: list[Trecho]) -> None:
    """Document, Chunks com embedding, PARTE_DE e PROXIMO."""
    db.run(
        "MERGE (d:Document {id: $id}) SET d.titulo = $titulo, d.tipo = $tipo, "
        "d.numero = $numero, d.ano = $ano, d.fonte = $fonte, d.url = $url, "
        "d.licenca = $licenca, d.hash = $hash",
        **{k: v for k, v in asdict(doc).items() if k != "texto"}, hash=doc.hash,
    )
    vetores = embed_batch([f"{doc.titulo}. {t.rotulo}. {t.texto}" for t in trechos])
    linhas = [{"id": t.id, "texto": t.texto, "ordem": t.ordem, "rotulo": t.rotulo, "emb": v}
              for t, v in zip(trechos, vetores)]
    for lote in _lotes(linhas):
        db.run(
            "MATCH (d:Document {id: $doc}) UNWIND $linhas AS l "
            "MERGE (c:Chunk {id: l.id}) SET c.texto = l.texto, c.ordem = l.ordem, "
            "c.rotulo = l.rotulo, c.doc_id = $doc, c.embedding = l.emb "
            "MERGE (c)-[:PARTE_DE]->(d)",
            doc=doc.id, linhas=lote,
        )
    db.run(
        "MATCH (d:Document {id: $doc})<-[:PARTE_DE]-(c:Chunk) WITH c ORDER BY c.ordem "
        "WITH collect(c) AS cs UNWIND range(0, size(cs) - 2) AS i "
        "WITH cs[i] AS a, cs[i + 1] AS b MERGE (a)-[:PROXIMO]->(b)",
        doc=doc.id,
    )


def gravar_extracao(ext: Extracao) -> None:
    """Grava entidades pela chave canônica, relações tipadas e menções."""
    ents = [{"key": e.key, "label": e.label, "nome": e.nome, "descricao": e.descricao,
             "props": e.props} for e in ext.entidades.values()]
    for lote in _lotes(ents):
        db.run(
            "UNWIND $ents AS e MERGE (n:Entity {key: e.key}) "
            "ON CREATE SET n.nome = e.nome, n.aliases = [] "
            "SET n:$(e.label), n += e.props, "
            "n.descricao = CASE WHEN coalesce(n.descricao, '') = '' THEN e.descricao "
            "ELSE n.descricao END",
            ents=lote,
        )
    rels = [{"id": r.id, "a": r.origem, "b": r.destino, "tipo": r.tipo, "fonte": r.fonte,
             "camada": r.camada, "conf": r.confianca, "ev": r.evidencia} for r in ext.relacoes]
    for lote in _lotes(rels):
        db.run(
            "UNWIND $rels AS r MATCH (a:Entity {key: r.a}), (b:Entity {key: r.b}) "
            "MERGE (a)-[x:$(r.tipo)]->(b) "
            "ON CREATE SET x.id = r.id, x.fontes = [], x.camada = r.camada, "
            "x.confianca = r.conf, x.evidencia = r.ev "
            "SET x.fontes = CASE WHEN r.fonte IN x.fontes THEN x.fontes ELSE x.fontes + r.fonte END, "
            "x.confianca = CASE WHEN r.conf > x.confianca THEN r.conf ELSE x.confianca END",
            rels=lote,
        )
    mencoes = [{"c": m.chunk_id, "k": m.key, "conf": m.confianca} for m in ext.mencoes]
    for lote in _lotes(mencoes):
        db.run(
            "UNWIND $ms AS m MATCH (c:Chunk {id: m.c}), (e:Entity {key: m.k}) "
            "MERGE (c)-[x:MENCIONA]->(e) "
            "SET x.confianca = CASE WHEN coalesce(x.confianca, 0) < m.conf THEN m.conf "
            "ELSE x.confianca END",
            ms=lote,
        )


def embeddings_de_entidades() -> int:
    """Calcula embedding das entidades novas ou cujo texto mudou."""
    linhas = db.run(
        "MATCH (e:Entity) WITH e, e.nome + ': ' + coalesce(e.descricao, '') AS txt "
        "WHERE e.embedding IS NULL OR e.texto_embedding <> txt RETURN e.key AS key, txt"
    )
    if not linhas:
        return 0
    vetores = embed_batch([r["txt"] for r in linhas])
    dados = [{"key": r["key"], "txt": r["txt"], "emb": v} for r, v in zip(linhas, vetores)]
    for lote in _lotes(dados):
        db.run(
            "UNWIND $d AS x MATCH (e:Entity {key: x.key}) "
            "SET e.embedding = x.emb, e.texto_embedding = x.txt",
            d=lote,
        )
    return len(dados)


def contagens() -> dict[str, dict[str, int]]:
    """Nós por rótulo e relações por tipo."""
    nos = db.run("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS n ORDER BY l")
    rels = db.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY t")
    return {"nos": {r["l"]: r["n"] for r in nos}, "relacoes": {r["t"]: r["n"] for r in rels}}
