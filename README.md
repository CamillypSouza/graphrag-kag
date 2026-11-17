# JuriGraph: pesquisa jurídica com GraphRAG e KAG sobre Neo4j

Projeto Final de Tendências em Ciência da Computação. O assistente responde perguntas sobre um corpus de
legislação brasileira (LGPD, Marco Civil da Internet, CDC, LAI, Lei do Superendividamento, Decretos 8.771/2016
e 7.962/2013) e temas de repercussão geral do STF. Ele combina três formas de recuperação: busca lexical
(fulltext), busca vetorial e travessia de grafo. Cada afirmação da resposta cita o nó ou a relação do grafo
que a sustenta.

| Pilar do enunciado | Onde está |
|---|---|
| Text-to-Graph | `src/jurigraph/ingestion/` (camada estrutural por regex + extração com LLM + resolução de entidades) |
| LPG no Neo4j | `src/jurigraph/schema/`, `docs/modelo.md` |
| Recuperação híbrida, multi-hop e algoritmos | `src/jurigraph/retrieval/`, `src/jurigraph/graph_algos/` |
| Anti-alucinação | `src/jurigraph/generation/` (citações, verificador, confiança) |
| Interface com rastreabilidade | `src/jurigraph/ui/app.py` |
| Avaliação | `src/jurigraph/eval/avaliar.py`, `docs/avaliacao.md` |
| Decisões de projeto | `docs/decisoes.md` |
| Artigo (SBC) | `docs/artigo/` |

## Pré-requisitos

- Docker (Neo4j 2026.10 com APOC e GDS sobem pelo compose)
- Python 3.11 ou mais novo
- Uma chave de API da OpenAI (o modelo padrão é `gpt-5.4-mini`; Anthropic e Ollama também funcionam pelo `.env`)
- Cerca de 3 GB livres (imagem do Neo4j, PyTorch e o modelo de embeddings)

Os embeddings rodam localmente (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensões) e não têm custo.

## Reprodução, passo a passo

```bash
# 1. Ambiente
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # preencha OPENAI_API_KEY; nunca versione o .env

# 2. Neo4j
docker compose up -d neo4j    # espere o healthcheck ficar "healthy"

# 3. Schema: constraints e índices range, fulltext e vetoriais (idempotente)
python -m jurigraph.schema.setup

# 4. Corpus: baixa do planalto.gov.br e do portal do STF para data/raw (pausa de 6 s entre pedidos)
python -m jurigraph.corpus

# 5. Ingestão Text-to-Graph (idempotente e retomável; documentos sem mudança são pulados)
python -m jurigraph.ingestion.pipeline            # --sem-llm faz só a camada estrutural

# 6. Algoritmos de grafo: PageRank, Leiden e resumos das maiores comunidades
python -m jurigraph.graph_algos.algos --resumos 30

# 7. Interface
streamlit run src/jurigraph/ui/app.py             # http://localhost:8501

# 8. Testes e avaliação
pytest -m "not neo4j and not llm"                 # unitários, sem rede
pytest                                            # todos (precisa do Neo4j)
python -m jurigraph.eval.avaliar                  # gera docs/avaliacao.md (gasta tokens)
```

As respostas da extração com LLM ficam em cache (`data/state/llm_extracao.jsonl`). Reingerir o mesmo corpus,
com o mesmo modelo e a mesma versão do prompt, não gera custo novo.

Com o `.env` pronto, a interface também roda em container: `docker compose --profile app up --build`.

## Custos observados

Os valores usam o preço configurado no `.env` (US$ 0,75 e US$ 4,50 por 1M tokens de entrada e de saída).

- Extração inicial dos 50 documentos: cerca de US$ 1,50 (413 chamadas).
- Resumos de comunidade: cerca de US$ 0,05.
- Uma pergunta: de US$ 0,002 (modo vetorial) a cerca de US$ 0,015 (modos híbrido e KAG).

## Os três modos

- **vetorial:** baseline de RAG tradicional, só com o índice vetorial dos trechos.
- **hibrido:** vetor e fulltext com ranker linear, mais expansão Cypher de 2 saltos a partir das entidades
  mencionadas, Text-to-Cypher validado e resumos de comunidade.
- **kag:** um planejador decompõe a pergunta em passos encadeados (busca, Cypher, caminho mínimo,
  comunidades) e executa os passos em ordem topológica.

Os três modos compartilham o gerador com citações e o verificador. Quando não há evidência suficiente, o sistema
responde "Não há evidência no grafo para responder a essa pergunta".

## Segurança do Text-to-Cypher

O Cypher gerado pelo LLM passa por várias barreiras antes de rodar:

- validador léxico: palavras de escrita bloqueadas fora de strings e comentários, `CALL` só da lista
  permitida, `LIMIT` obrigatório;
- `EXPLAIN` antes de executar;
- sessão em modo `READ`, para que o servidor recuse qualquer escrita;
- timeout por transação.

Os casos de ataque estão em `tests/test_cypher_guard.py`.

## Aviso

Ferramenta acadêmica de pesquisa. Não é aconselhamento jurídico.
