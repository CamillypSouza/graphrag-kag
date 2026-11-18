"""Constraints e índices do Neo4j, todos com IF NOT EXISTS."""

from dataclasses import dataclass

from jurigraph.config import get_settings


@dataclass(frozen=True)
class Ddl:
    nome: str
    tipo: str  # constraint, range, fulltext ou vector
    cypher: str


def constraints() -> list[Ddl]:
    """Unicidade das chaves de Document, Chunk, Entity e Community."""
    alvos = [("document_id", "Document", "id"), ("chunk_id", "Chunk", "id"),
             ("entity_key", "Entity", "key"), ("community_id", "Community", "id")]
    return [
        Ddl(nome, "constraint",
            f"CREATE CONSTRAINT {nome} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE")
        for nome, label, prop in alvos
    ]


def range_indexes() -> list[Ddl]:
    """Índices de faixa (B-tree) nas propriedades usadas em filtro e ordenação."""
    nos = [("document_tipo", "Document", "tipo"), ("document_ano", "Document", "ano"),
           ("lei_numero", "Lei", "numero"), ("artigo_numero", "Artigo", "numero"),
           ("precedente_numero", "Precedente", "numero"), ("entity_pagerank", "Entity", "pagerank"),
           ("entity_comunidade", "Entity", "comunidade"), ("entity_nome", "Entity", "nome")]
    ddls = [Ddl(n, "range", f"CREATE INDEX {n} IF NOT EXISTS FOR (x:{l}) ON (x.{p})")
            for n, l, p in nos]
    ddls.append(Ddl("menciona_confianca", "range",
                    "CREATE INDEX menciona_confianca IF NOT EXISTS "
                    "FOR ()-[r:MENCIONA]-() ON (r.confianca)"))
    return ddls


def fulltext_indexes() -> list[Ddl]:
    """Busca lexical (Lucene/BM25) com analisador para português do Brasil."""
    cfg = "OPTIONS {indexConfig: {`fulltext.analyzer`: 'brazilian'}}"
    return [
        Ddl("entity_text", "fulltext",
            f"CREATE FULLTEXT INDEX entity_text IF NOT EXISTS FOR (n:Entity) "
            f"ON EACH [n.nome, n.descricao] {cfg}"),
        Ddl("chunk_text", "fulltext",
            f"CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (n:Chunk) ON EACH [n.texto] {cfg}"),
    ]


def vector_indexes() -> list[Ddl]:
    """Índices vetoriais com a dimensão do modelo de embedding configurado."""
    dim = get_settings().embedding_dimensions
    cfg = ("OPTIONS {indexConfig: {`vector.dimensions`: %d, "
           "`vector.similarity_function`: 'cosine'}}" % dim)
    return [
        Ddl(nome, "vector",
            f"CREATE VECTOR INDEX {nome} IF NOT EXISTS FOR (n:{label}) ON n.embedding {cfg}")
        for nome, label in [("chunk_embedding", "Chunk"), ("entity_embedding", "Entity"),
                            ("community_embedding", "Community")]
    ]


def all_ddl() -> list[Ddl]:
    """Toda a DDL, constraints primeiro."""
    return constraints() + range_indexes() + fulltext_indexes() + vector_indexes()
