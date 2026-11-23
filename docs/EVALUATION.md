# Evaluation framework

The evaluation measures the shipped code. `python -m eval.run` uses the production parsers, chunkers,
embedder, Qdrant store, BM25 index, RRF fusion, cross-encoder, prompt, relevance gate and citation
parser. Only the orchestration (looping over questions and configurations) is evaluation-specific.

## Dataset

* **Corpus** (`backend/eval/corpus_src/` → rendered into `backend/eval/corpus/`): 13 documents for a fictional
  company, written for this benchmark, rendered to **4 PDF, 4 DOCX, 2 TXT and 3 Markdown** files. The set
  includes realistic difficulties:
  * two versions each of the travel policy (2023 / 2024) and security policy (v3 2022 / v4 2024) that differ
    in specific values, so an unfiltered search often finds the wrong version;
  * facts that live only in tables (hotel caps, revenue by segment, SLA response times, approval
    thresholds, retention periods);
  * exact identifiers that favour keyword search (`HX-1201`, `helixctl rollback`, `CREATE VECTOR INDEX`);
  * overlapping topics across documents (leave, travel, security, incidents).
* **Questions** (`backend/eval/dataset/questions.jsonl`): **135** questions: 125 answerable and 10
  unanswerable. Types: factual 66, versioned 25, table 12, numeric 8, keyword 7, paraphrase 3, conversational
  follow-up 4 (with prior turns), unanswerable 10. 32 questions carry user-supplied metadata filters
  (document, category or date range) like a user would set in the UI.
* Each answerable question has a reference answer, **key facts** that a correct answer must contain, and one
  or more **evidence spans**. `python -m eval.build_corpus` fails if any evidence span is not a verbatim
  substring of its document, and computes **gold page numbers** from the rendered files (PDF text search;
  DOCX page breaks).

## Configurations compared

| # | Name | Chunking | Retrieval | Rerank | Filters |
|---|---|---|---|---|---|
| 1 | `basic_vector` | fixed 1000 characters, raw text | dense | – | – |
| 2 | `chunking_vector` | structure-aware, heading context | dense | – | – |
| 3 | `hybrid` | structure-aware | dense + BM25, RRF (k = 60) | – | – |
| 4 | `hybrid_rerank` | structure-aware | dense + BM25, RRF | cross-encoder over top 30 + relevance gate | – |
| 5 | `hybrid_rerank_filter` | structure-aware | dense + BM25, RRF | cross-encoder + relevance gate | question's filters |

Each configuration retrieves 10 chunks (for Recall@10). The top 5 go to the LLM.

## Metrics

| Metric | Definition |
|---|---|
| Recall@K | Share of the question's gold evidence spans covered by the top-K chunks. A chunk covers a span if it comes from the span's document and contains ≥ 70 % of the span's content tokens (chunking-agnostic). |
| Precision@K | Share of the top-K chunks that cover any evidence span. With one gold span per question and many small chunks the ceiling is ≈ 1/K, so compare configurations relative to each other. |
| MRR | 1 / rank of the first relevant chunk (0 if none in the top 10). |
| Top-1 correct document | The first chunk comes from a gold document (shows version mix-ups). |
| Answer correctness | All key facts present in the answer (numbers normalised, whole-number match). Unanswerable questions are correct only if the system refuses. |
| Faithfulness | Share of answer sentences entailed (p ≥ 0.5) by at least one of the 5 context passages, judged by the `cross-encoder/nli-deberta-v3-xsmall` NLI model. Computed for non-refused answers. |
| Citation precision | Share of cited passages `[n]` that contain gold evidence. |
| Citation page accuracy | Share of cited passages whose document + page range include a gold page. |
| Correct refusals / false refusals | Refusal rate on unanswerable / answerable questions. |
| Latency | Wall-clock retrieval + generation per query, p50/p95. |
| Cost per query | *Actual*: what the run paid (local model = $0). *Projected*: measured tokens × configured API price (`PRICE_INPUT_PER_M`, `PRICE_OUTPUT_PER_M`). |

Recall@5, MRR and answer correctness also get 95 % bootstrap confidence intervals.

## Running it

```bash
cd backend
python -m eval.run --no-generation          # retrieval metrics only (~2 min on CPU)
python -m eval.run                          # full run with the configured LLM
OPENAI_API_KEY=sk-... python -m eval.run --run-name openai_gpt4o_mini   # same benchmark with OpenAI
python -m eval.run --llm-rpm 15                                         # pace calls for free-tier quotas
```

Results go to `backend/eval/results/<run>.json` and a Markdown report with charts to `docs/benchmarks/`.
Import them into the dashboard with **Evaluation → Import** (or `POST /api/v1/eval/import`). Generations
are checkpointed in `eval/results/.gen_cache_*.jsonl`, so an interrupted run resumes where it stopped and
re-scoring after a metric change needs no new LLM calls.

## Honest limitations

* The corpus is synthetic and small (13 documents, 115 structured chunks). It is designed to exercise
  failure modes, not to represent a production corpus; absolute scores on real data will be lower.
* Metadata filters in configuration 5 come from the dataset (user-set filters), not from automatic query
  understanding.
* Key-fact matching can mark a correct paraphrase as wrong (e.g. "twice yearly" vs "twice a year");
  the per-question browser on the Evaluation page shows every answer, so such cases can be checked.
* The included full run generates answers with Google Gemini 2.5 Flash (free tier, thinking disabled),
  paced to 15 requests per minute. Generation latency therefore includes network round-trips to Google
  and is not comparable to a self-hosted model. Re-run with another provider's settings to compare models
  on the same benchmark.
