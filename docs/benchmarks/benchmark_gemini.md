# Benchmark report — `benchmark_gemini`

Generated 2026-11-22T08:40:37.265860+00:00 by `python -m eval.run`. Every number below is computed from `backend/eval/results/benchmark_gemini.json`; nothing was edited by hand.

## Setup

* Questions: **135** (125 answerable, 10 unanswerable, 32 with user-supplied metadata filters)
* Embeddings `BAAI/bge-small-en-v1.5` · reranker `cross-encoder/ms-marco-MiniLM-L-6-v2` · faithfulness NLI `cross-encoder/nli-deberta-v3-base`
* LLM: `gemini-3.1-flash-lite` (openai_compatible) on cpu with 4 CPU cores
* Context passages given to the LLM: 5; retrieval depth 10; abstention gate: best reranker score < -4.0
* Index: `fixed` chunking → 39 chunks (avg 176.7 tokens); `structured` chunking → 115 chunks (avg 56.4 tokens)

## Retrieval (all answerable questions)

![retrieval](benchmark_gemini_retrieval.png)

| Configuration | Recall@1 | Recall@3 | Recall@5 (95% CI) | Recall@10 | Precision@5 | MRR (95% CI) | Top-1 correct doc | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| 1. Basic vector search | 0.676 | 0.936 | 0.968 (0.94–0.99) | 0.976 | 0.208 | 0.801 (0.75–0.86) | 0.832 | 32.2 | 42.3 |
| 2. Improved chunking + vector | 0.824 | 0.952 | 0.976 (0.94–1.00) | 0.992 | 0.195 | 0.894 (0.85–0.93) | 0.904 | 31.6 | 41.5 |
| 3. Hybrid (BM25 + vector, RRF) | 0.832 | 0.968 | 0.984 (0.96–1.00) | 1.000 | 0.197 | 0.903 (0.86–0.94) | 0.912 | 32.9 | 40.3 |
| 4. Hybrid + reranking | 0.904 | 1.000 | 1.000 (1.00–1.00) | 1.000 | 0.200 | 0.951 (0.92–0.97) | 0.936 | 347.8 | 447.5 |
| 5. Hybrid + reranking + filters | 0.936 | 1.000 | 1.000 (1.00–1.00) | 1.000 | 0.200 | 0.967 (0.94–0.99) | 0.968 | 340.9 | 444.6 |

### Questions with metadata filters (n = 32)

These are mostly *versioned* questions (e.g. the 2023 vs 2024 travel policy), where an unfiltered search tends to return the wrong version.

![filtered](benchmark_gemini_retrieval_filtered.png)

| Configuration | Recall@1 | Recall@5 | Precision@5 | MRR | Top-1 correct doc |
|---|---|---|---|---|---|
| 1. Basic vector search | 0.406 | 1.000 | 0.219 | 0.637 | 0.594 |
| 2. Improved chunking + vector | 0.781 | 1.000 | 0.200 | 0.891 | 0.812 |
| 3. Hybrid (BM25 + vector, RRF) | 0.781 | 1.000 | 0.200 | 0.885 | 0.812 |
| 4. Hybrid + reranking | 0.875 | 1.000 | 0.200 | 0.938 | 0.875 |
| 5. Hybrid + reranking + filters | 1.000 | 1.000 | 0.200 | 1.000 | 1.000 |

### MRR by question type

| Configuration | factual (n=66) | followup (n=4) | keyword (n=7) | numeric (n=8) | paraphrase (n=3) | table (n=12) | versioned (n=25) |
|---|---|---|---|---|---|---|---|
| 1. Basic vector search | 0.835 | 0.750 | 1.000 | 0.917 | 0.500 | 0.833 | 0.648 |
| 2. Improved chunking + vector | 0.902 | 1.000 | 1.000 | 0.719 | 1.000 | 0.833 | 0.900 |
| 3. Hybrid (BM25 + vector, RRF) | 0.922 | 1.000 | 1.000 | 0.688 | 1.000 | 0.854 | 0.893 |
| 4. Hybrid + reranking | 0.970 | 1.000 | 1.000 | 0.854 | 1.000 | 0.917 | 0.920 |
| 5. Hybrid + reranking + filters | 0.970 | 1.000 | 1.000 | 0.854 | 1.000 | 0.917 | 1.000 |

## Answer quality, latency and cost

![answers](benchmark_gemini_answers.png)

| Configuration | Correctness (95% CI) | Key-fact recall | Faithfulness | Citation precision | Citation page acc. | Correct refusals | False refusals | p50 latency ms | p95 latency ms | Tokens in/out | Cost/query (actual) | Cost/query (projected) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. Basic vector search | 0.936 (0.89–0.98) | 0.949 | 0.074 | 0.967 | 0.984 | 100.0% | 2.4% | 3790 | 5124 | 1471 / 26 | $0.000000 | $0.000200 |
| 2. Improved chunking + vector | 0.936 (0.89–0.98) | 0.949 | 0.646 | 0.980 | 0.984 | 100.0% | 2.4% | 4043 | 5929 | 787 / 26 | $0.000000 | $0.000100 |
| 3. Hybrid (BM25 + vector, RRF) | 0.944 (0.90–0.98) | 0.952 | 0.641 | 0.980 | 0.984 | 100.0% | 1.6% | 4098 | 5066 | 782 / 26 | $0.000000 | $0.000100 |
| 4. Hybrid + reranking | 0.952 (0.91–0.98) | 0.965 | 0.648 | 0.976 | 0.980 | 100.0% | 0.0% | 4024 | 4952 | 768 / 26 | $0.000000 | $0.000100 |
| 5. Hybrid + reranking + filters | 0.960 (0.93–0.99) | 0.968 | 0.540 | 0.968 | 0.980 | 100.0% | 0.0% | 3993 | 4969 | 765 / 25 | $0.000000 | $0.000100 |

*Actual* cost uses the configured price of the model that ran ($0.0/1M input, $0.0/1M output; $0 for local models and free tiers). *Projected* cost applies a reference API price ($0.15/1M input, $0.6/1M output — gpt-4o-mini list pricing by default, set `PROJECTED_PRICE_INPUT_PER_M`/`PROJECTED_PRICE_OUTPUT_PER_M`) to the token counts measured in this run, so it is an estimate.

## Metric definitions

* **Relevant chunk**: from the gold document and contains ≥70% of a gold evidence span's content tokens (chunking-agnostic, so fixed and structured chunks are judged against the same evidence).
* **Recall@K**: share of a question's gold evidence spans covered by the top-K chunks. **Precision@K**: share of the top-K chunks that are relevant. **MRR**: 1/rank of the first relevant chunk.
* **Answer correctness**: all key facts of the reference answer appear in the generated answer (numbers normalized); unanswerable questions count as correct only when the system refuses.
* **Faithfulness**: share of answer sentences entailed (p ≥ 0.5) by at least one retrieved passage, scored by the NLI cross-encoder.
* **Citation precision**: share of cited passages `[n]` that contain gold evidence. **Citation page accuracy**: share of cited passages whose document and page range contain a gold page.
* **Latency**: measured wall-clock retrieval + generation for each query on this machine. When two configurations retrieve the identical top-5 for a question, the generation is computed once and its measured time is reused.

## Limitations

* The corpus is a purpose-built synthetic set of 13 enterprise documents (fictional company), written for this benchmark with exact evidence spans; absolute numbers will differ on real corpora.
* Metadata filters in configuration 5 are the filters a user would set in the UI (stored per question); they are not inferred automatically from the question text.
* Answer correctness uses key-fact matching, which can miss correct paraphrases of a fact.
