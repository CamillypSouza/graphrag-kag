# Avaliação

Gerado por `python -m jurigraph.eval.avaliar` em 17/11/2026 16:47.
Perguntas: 32 (`data/eval/perguntas.jsonl`). Modelo: `gpt-5.4-mini`. Embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
Resultados por pergunta: `data/eval/resultados.jsonl`.

Os três modos usam o mesmo gerador e o mesmo verificador; só a recuperação muda.
O custo usa o preço configurado (US$ 0.75/4.5 por 1M tokens de
entrada/saída) e não inclui o juiz da avaliação.

## Resultado geral

| Métrica | RAG vetorial puro (baseline) | GraphRAG híbrido (vetor + fulltext + 2 saltos + Text-to-Cypher + comunidades) | GraphRAG com planejador estilo KAG |
|---|---|---|---|
| Acerto (respondíveis) | 74.1% | 72.2% | 53.7% |
| Acerto (impossíveis = recusa) | 100.0% | 100.0% | 100.0% |
| Palavras-chave presentes | 77.8% | 66.7% | 55.6% |
| Alucinação bruta (afirmações não sustentadas) | 17.7% | 27.8% | 34.4% |
| Impossíveis respondidas | 0.0% | 0.0% | 0.0% |
| Fidelidade das citações | 100.0% | 78.4% | 83.8% |
| Recusas em respondíveis | 14.8% | 18.5% | 22.2% |
| Latência média (s) | 5.0 | 6.7 | 7.9 |
| Latência p95 (s) | 11.2 | 9.9 | 19.4 |
| Custo total (US$) | 0.110 | 0.371 | 0.225 |
| Custo médio por pergunta (US$) | 0.0034 | 0.0116 | 0.0070 |

## Acerto por tipo de pergunta

| Tipo de pergunta | RAG vetorial puro (baseline) | GraphRAG híbrido (vetor + fulltext + 2 saltos + Text-to-Cypher + comunidades) | GraphRAG com planejador estilo KAG |
|---|---|---|---|
| Um salto | 75.0% | 75.0% | 50.0% |
| Multi-hop | 83.3% | 83.3% | 58.3% |
| Global | 50.0% | 40.0% | 50.0% |
| Impossível | 100.0% | 100.0% | 100.0% |

## Como ler

- **Acerto:** veredito de um juiz LLM contra a resposta esperada (correta = 1, parcial = 0,5). Nas
  perguntas impossíveis, acerto significa recusar ("não há evidência no grafo").
- **Alucinação bruta:** afirmações que o gerador produziu e o verificador não conseguiu sustentar no
  contexto. Elas são removidas antes da resposta final; o número mede o quanto o verificador precisou agir.
- **Impossíveis respondidas:** a falha mais grave, uma resposta dada sem base no corpus.
- **Fidelidade das citações:** afirmações cujas citações apontam para ids presentes no subgrafo recuperado.
- **Limitações:** o juiz é o mesmo modelo que gera as respostas, e o conjunto de perguntas é pequeno e foi
  escrito pela equipe a partir do próprio corpus.
- **Análise dos resultados:** `docs/artigo/discussao.tex`.
