# Avaliação

Gerado por `python -m jurigraph.eval.avaliar` em 18/11/2026 19:35.
Perguntas: 32 (`data/eval/perguntas.jsonl`). Modelo: `gpt-5.4-mini`. Embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
Resultados por pergunta: `data/eval/resultados.jsonl`.

Os três modos usam o mesmo gerador e o mesmo verificador; só a recuperação muda.
O custo usa o preço configurado (US$ 0.75/4.5 por 1M tokens de
entrada/saída) e não inclui o juiz da avaliação.

## Resultado geral

| Métrica | RAG vetorial puro (baseline) | GraphRAG híbrido (vetor + fulltext + 2 saltos + Text-to-Cypher + comunidades) | GraphRAG com planejador estilo KAG |
|---|---|---|---|
| Acerto (respondíveis) | 74.1% | 83.3% | 74.1% |
| Acerto (impossíveis = recusa) | 100.0% | 100.0% | 100.0% |
| Palavras-chave presentes | 77.8% | 85.2% | 77.8% |
| Alucinação bruta (afirmações não sustentadas) | 18.7% | 20.7% | 16.2% |
| Impossíveis respondidas | 0.0% | 0.0% | 0.0% |
| Fidelidade das citações | 75.0% | 78.1% | 81.2% |
| Recusas em respondíveis | 11.1% | 7.4% | 3.7% |
| Latência média (s) | 4.5 | 8.0 | 6.9 |
| Latência p95 (s) | 8.0 | 12.7 | 11.0 |
| Custo total (US$) | 0.124 | 0.404 | 0.284 |
| Custo médio por pergunta (US$) | 0.0039 | 0.0126 | 0.0089 |

## Acerto por tipo de pergunta

| Tipo de pergunta | RAG vetorial puro (baseline) | GraphRAG híbrido (vetor + fulltext + 2 saltos + Text-to-Cypher + comunidades) | GraphRAG com planejador estilo KAG |
|---|---|---|---|
| Um salto | 75.0% | 90.0% | 70.0% |
| Multi-hop | 83.3% | 87.5% | 87.5% |
| Global | 50.0% | 60.0% | 50.0% |
| Impossível | 100.0% | 100.0% | 100.0% |

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
