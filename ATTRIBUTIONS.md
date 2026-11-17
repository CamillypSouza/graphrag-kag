# Atribuições

## Corpus

Textos de lei e decisões judiciais não são protegidos por direito autoral (Lei 9.610/1998, art. 8º, IV). A lista
completa, com URL de cada documento, está em `data/raw/FONTES.md`.

- Presidência da República, portal da legislação (planalto.gov.br):
  - Lei 13.709/2018 (LGPD)
  - Lei 12.965/2014 (Marco Civil da Internet)
  - Lei 8.078/1990 (CDC)
  - Lei 12.527/2011 (LAI)
  - Lei 14.181/2021
  - Decreto 8.771/2016
  - Decreto 7.962/2013
- Supremo Tribunal Federal, portal de repercussão geral: Temas 210, 533, 987, 1093 e 1141.

## Software

| Componente | Versão | Licença |
|---|---|---|
| Neo4j Community Edition | 2026.10.2 | GPL-3.0 |
| APOC Core | 2026.10.2 | Apache-2.0 |
| Neo4j Graph Data Science (Community) | 2026.10.2 | GPL-3.0 |
| neo4j (driver Python) | 6.4.1 | Apache-2.0 |
| neo4j-graphrag | 1.24.0 | Apache-2.0 |
| neo4j-viz | 1.13.0 | GPL-3.0-only |
| streamlit | 1.67.0 | Apache-2.0 |
| sentence-transformers | 6.3.0 | Apache-2.0 |
| openai (SDK) | 3.52.0 | Apache-2.0 |
| rapidfuzz | 3.14.6 | MIT |
| networkx | 3.7 | BSD-3-Clause |
| pandas | 3.1.1 | BSD-3-Clause |
| pydantic-settings | 2.16.3 | MIT |
| beautifulsoup4 | 4.15.0 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| pytest | 9.2.0 | MIT |

O `neo4j-viz` é GPL-3.0. Se o código for redistribuído, a licença do projeto precisa ser compatível com ela. Outra
saída é trocar a visualização por uma biblioteca permissiva.

## Modelos

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Apache-2.0, usado para os embeddings.
- OpenAI `gpt-5.4-mini`, pela API, nos termos de uso da OpenAI. Faz a extração, o Text-to-Cypher, o
  planejamento, a geração, a verificação e o papel de juiz na avaliação.

## Referências de método

- Edge et al., *From Local to Global: A Graph RAG Approach to Query-Focused Summarization* (Microsoft, 2024):
  resumos de comunidade para perguntas globais.
- Liang et al., *KAG: Boosting LLMs in Professional Domains via Knowledge Augmented Generation* (Ant Group, 2024):
  planejamento lógico sobre o grafo.
- Sarmah et al., *HybridRAG: Integrating Knowledge Graphs and Vector Retrieval Augmented Generation* (2024).
- Traag, Waltman e van Eck, *From Louvain to Leiden: guaranteeing well-connected communities* (2019).
- Page et al., *The PageRank Citation Ranking* (1999).
