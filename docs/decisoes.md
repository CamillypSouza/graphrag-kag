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
| D10 | 17/11/2026 | Jurisprudência vem dos temas de repercussão geral do STF; `Sumula` virou `Precedente {tipo, numero, tribunal}` | O portal de súmulas do STJ exige um desafio do Cloudflare, que não foi contornado. Temas fora do escopo são filtrados por palavras-chave |
| D11 | 17/11/2026 | O download guarda o HTML bruto em cache e decodifica em utf-8 ou windows-1252 | O planalto bloqueou por algum tempo após uma rajada de requisições e não declara o charset no começo da página |
| D12 | 17/11/2026 | Resolução de entidades conservadora: só funde variações de forma (plural, acento, preposição) ou termo genérico a mais; troca de termo nunca funde; embedding exige apoio léxico (`token_set_ratio` ≥ 70) | Fusões erradas observadas na primeira rodada: "segurança pública" × "segurança do Estado", "produto" × "produtor", Ministérios Públicos distintos. Em direito, precisão vale mais que cobertura |
| D13 | 17/11/2026 | GDS chamado por procedimentos Cypher (`gds.graph.project`, `gds.pageRank.write`, `gds.leiden.write`), sem o cliente Python `graphdatascience` | O cliente 2.3 está migrando de API (`graph.project` virou objeto, parâmetros renomeados). A API de procedimentos do servidor é estável e documentada |
| D14 | 17/11/2026 | Preço de `gpt-5.4-mini` em US$ 0,75 (entrada) e US$ 4,50 (saída) por 1M tokens | Valores de agregadores de preço; a página oficial da OpenAI não abriu. O custo informado é estimativa |
