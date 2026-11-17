# Registro de decisões

| # | Data | Decisão | Motivo |
|---|---|---|---|
| D1 | 17/11/2026 | Domínio: assistente de pesquisa jurídica (LGPD, Marco Civil, CDC, LAI, súmulas e teses) | Escolha do grupo. Textos de lei e decisões judiciais são públicos e sem proteção autoral (Lei 9.610/98, art. 8º, IV) e têm estrutura rica em remissões, boa para multi-hop |
| D2 | 17/11/2026 | LLM: OpenAI `gpt-5.4-mini`, trocável por `LLM_PROVIDER` e `LLM_MODEL` | O enunciado exige LLM ("combinar Neo4j com LLMs", Fase 3 "geração de Cypher via LLM"). O mini mantém o custo baixo |
| D3 | 17/11/2026 | Embeddings locais `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, cosseno) | Corpus em português, sem custo, roda em CPU; `text-embedding-3-small` fica como opção |
| D4 | 17/11/2026 | Neo4j `2026.10.2-community` com APOC e GDS no Docker, heap de 1 GB | Última versão estável. A máquina de desenvolvimento tem 8 GB de RAM |
| D5 | 17/11/2026 | Cypher 25 (padrão do servidor) e analisador fulltext `brazilian` | Conferido com `db.query.default_language` e `db.index.fulltext.listAvailableAnalyzers()` |
| D6 | 17/11/2026 | Extração em duas camadas: regras para a estrutura (lei, artigo, súmula, remissões) e LLM para a semântica | Remissões legais seguem padrão fixo. Regras são exatas e baratas e deixam o LLM só para o que é aberto |
| D7 | 17/11/2026 | Componentes do neo4j-graphrag (`LLMEntityRelationExtractor`, retrievers) em vez do `SimpleKGPipeline` fechado | Controle da chave canônica, da ligação Chunk→Entity e da resolução de entidades |
| D8 | 17/11/2026 | App roda no venv local; o serviço `app` do compose fica num perfil opcional | Disco limitado na máquina de desenvolvimento (uma imagem com PyTorch passa de 2 GB) |
| D9 | 17/11/2026 | Pacote Python único `jurigraph` em `src/` | Evita conflito de nomes genéricos (`config`, `schema`) com outras bibliotecas |
