"""Markdown + PNG report generated from an eval results JSON (no numbers are typed by hand)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

INK, INK2, GRID, SURFACE, BAR, BAR_BEST = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#9cc1ee", "#2a78d6"


def _fmt(v, pct=False, digits=3):
    if v is None:
        return "–"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


def _chart(summary: dict, metrics: list[tuple[str, str, bool]], path: Path, subset: str = "overall"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(summary)
    short = [summary[n]["label"].split(". ", 1)[0] for n in names]
    cols = 3
    rows = (len(metrics) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.0 * rows), facecolor=SURFACE)
    for ax, (key, title, higher_better) in zip(axes.flat, metrics):
        vals = [summary[n][subset].get(key) for n in names]
        nums = [v if v is not None else 0 for v in vals]
        valid = [v for v in vals if v is not None]
        best = (max if higher_better else min)(valid) if valid else None
        colors = [BAR_BEST if v is not None and v == best else BAR for v in vals]
        bars = ax.bar(short, nums, color=colors, width=0.6, edgecolor=SURFACE, linewidth=2)
        ax.set_facecolor(SURFACE)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=8, length=0)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        top = max(nums) if nums and max(nums) > 0 else 1
        ax.set_ylim(0, top * 1.22)
        for b, v in zip(bars, vals):
            if v is not None:
                label = f"{v:.0f}" if v >= 100 else (f"{v:.2f}" if v < 10 else f"{v:.1f}")
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + top * 0.03, label, ha="center",
                        fontsize=8, color=INK)
    for ax in list(axes.flat)[len(metrics):]:
        ax.axis("off")
    fig.text(0.01, 0.005, "Configurations: " + "  ".join(f"{s} = {summary[n]['label'].split('. ', 1)[1]}"
                                                         for s, n in zip(short, names)),
             fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


RETRIEVAL = [("recall@5", "Recall@5", True), ("precision@5", "Precision@5", True), ("mrr", "MRR", True),
             ("recall@1", "Recall@1", True), ("top1_doc_correct", "Top-1 from correct document", True),
             ("retrieval_ms_p50", "Retrieval latency p50 (ms)", False)]
ANSWER = [("answer_correctness", "Answer correctness", True), ("faithfulness", "Faithfulness (NLI)", True),
          ("citation_precision", "Citation precision", True),
          ("citation_page_accuracy", "Citation page accuracy", True),
          ("unanswerable_abstention_rate", "Correct refusals (unanswerable)", True),
          ("latency_ms_p50", "End-to-end latency p50 (ms)", False)]


def write_report(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    s, env, name = result["summary"], result["environment"], result["run_name"]
    _chart(s, RETRIEVAL, out_dir / f"{name}_retrieval.png")
    _chart(s, RETRIEVAL[:5], out_dir / f"{name}_retrieval_filtered.png", subset="with_filters")
    gen = env.get("generation")
    if gen:
        _chart(s, ANSWER, out_dir / f"{name}_answers.png")
    L = [f"# Benchmark report — `{name}`", "",
         f"Generated {result['created_at']} by `python -m eval.run`. Every number below is computed from "
         f"`backend/eval/results/{name}.json`; nothing was edited by hand.", "",
         "## Setup", "",
         f"* Questions: **{env['n_questions']}** ({env['n_answerable']} answerable, "
         f"{env['n_questions'] - env['n_answerable']} unanswerable, {env['n_with_filters']} with user-supplied metadata filters)",
         f"* Embeddings `{env['embedding_model']}` · reranker `{env['reranker_model']}` · faithfulness NLI `{env['nli_model']}`",
         f"* LLM: `{env.get('llm')}` ({env.get('llm_provider')}) on {env['device']} with {env['cpu_count']} CPU cores"
         if gen else "* Retrieval-only run (no generation)",
         f"* Context passages given to the LLM: {env['context_k']}; retrieval depth {env['retrieve_k']}; "
         f"abstention gate: best reranker score < {env['abstain_threshold']}",
         "* Index: " + "; ".join(f"`{k}` chunking → {v['chunks']} chunks (avg {v['avg_tokens']} tokens)"
                                  for k, v in env["index"].items()), ""]
    L += ["## Retrieval (all answerable questions)", "", f"![retrieval]({name}_retrieval.png)", "",
          "| Configuration | Recall@1 | Recall@3 | Recall@5 (95% CI) | Recall@10 | Precision@5 | MRR (95% CI) | Top-1 correct doc | p50 ms | p95 ms |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for n, v in s.items():
        o = v["overall"]
        ci = lambda k: f" ({o[k][0]:.2f}–{o[k][1]:.2f})" if o.get(k) else ""  # noqa: E731
        L.append(f"| {v['label']} | {_fmt(o['recall@1'])} | {_fmt(o['recall@3'])} | {_fmt(o['recall@5'])}{ci('recall@5_ci95')} | "
                 f"{_fmt(o['recall@10'])} | {_fmt(o['precision@5'])} | {_fmt(o['mrr'])}{ci('mrr_ci95')} | "
                 f"{_fmt(o['top1_doc_correct'])} | {_fmt(o['retrieval_ms_p50'], digits=1)} | {_fmt(o['retrieval_ms_p95'], digits=1)} |")
    L += ["", f"### Questions with metadata filters (n = {next(iter(s.values()))['with_filters']['n_answerable']})", "",
          "These are mostly *versioned* questions (e.g. the 2023 vs 2024 travel policy), where an unfiltered search "
          "tends to return the wrong version.", "", f"![filtered]({name}_retrieval_filtered.png)", "",
          "| Configuration | Recall@1 | Recall@5 | Precision@5 | MRR | Top-1 correct doc |", "|---|---|---|---|---|---|"]
    for n, v in s.items():
        o = v["with_filters"]
        L.append(f"| {v['label']} | {_fmt(o['recall@1'])} | {_fmt(o['recall@5'])} | {_fmt(o['precision@5'])} | "
                 f"{_fmt(o['mrr'])} | {_fmt(o['top1_doc_correct'])} |")
    types = sorted({t for v in s.values() for t in v["by_type"]} - {"unanswerable"})
    L += ["", "### MRR by question type", "", "| Configuration | " + " | ".join(
        f"{t} (n={next(iter(s.values()))['by_type'][t]['n']})" for t in types) + " |",
          "|---|" + "---|" * len(types)]
    for n, v in s.items():
        L.append(f"| {v['label']} | " + " | ".join(_fmt(v["by_type"][t]["mrr"]) for t in types) + " |")
    if gen and env.get("generation_latency_includes_pacing"):
        L += ["", f"> **Latency caveat for this run.** Answers were generated through a free-tier API throttled "
              f"client-side to {env.get('llm_rpm')} requests/minute, and the recorded generation time includes that "
              "wait (about 60 / rpm seconds per call). End-to-end latency below is therefore dominated by the throttle "
              "and is **not** representative of the system; retrieval latency is unaffected. Runs made with the "
              "current runner subtract pacing time automatically."]
    if gen:
        L += ["", "## Answer quality, latency and cost", "", f"![answers]({name}_answers.png)", "",
              "| Configuration | Correctness (95% CI) | Key-fact recall | Faithfulness | Citation precision | Citation page acc. | Correct refusals | False refusals | p50 latency ms | p95 latency ms | Tokens in/out | Cost/query (actual) | Cost/query (projected) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for n, v in s.items():
            o = v["overall"]
            ci = f" ({o['answer_correctness_ci95'][0]:.2f}–{o['answer_correctness_ci95'][1]:.2f})" if o.get("answer_correctness_ci95") else ""
            L.append(f"| {v['label']} | {_fmt(o['answer_correctness'])}{ci} | {_fmt(o['key_fact_recall'])} | "
                     f"{_fmt(o['faithfulness'])} | {_fmt(o['citation_precision'])} | {_fmt(o['citation_page_accuracy'])} | "
                     f"{_fmt(o['unanswerable_abstention_rate'], pct=True)} | {_fmt(o['false_abstention_rate'], pct=True)} | "
                     f"{_fmt(o['latency_ms_p50'], digits=0)} | {_fmt(o['latency_ms_p95'], digits=0)} | "
                     f"{_fmt(o['prompt_tokens_mean'], digits=0)} / {_fmt(o['completion_tokens_mean'], digits=0)} | "
                     f"${o['cost_per_query_usd']:.6f} | ${o['projected_cost_per_query_usd']:.6f} |")
        p = env.get("projected_price_per_m_tokens", env["price_per_m_tokens"])
        a = env["price_per_m_tokens"]
        L += ["", f"*Actual* cost uses the configured price of the model that ran (${a['input']}/1M input, "
              f"${a['output']}/1M output; $0 for local models and free tiers). *Projected* cost applies a reference "
              f"API price (${p['input']}/1M input, ${p['output']}/1M output — gpt-4o-mini list pricing by default, "
              "set `PROJECTED_PRICE_INPUT_PER_M`/`PROJECTED_PRICE_OUTPUT_PER_M`) to the token counts measured in this "
              "run, so it is an estimate.", ""]
    L += ["## Metric definitions", "",
          "* **Relevant chunk**: from the gold document and contains ≥70% of a gold evidence span's content tokens "
          "(chunking-agnostic, so fixed and structured chunks are judged against the same evidence).",
          "* **Recall@K**: share of a question's gold evidence spans covered by the top-K chunks. **Precision@K**: "
          "share of the top-K chunks that are relevant. **MRR**: 1/rank of the first relevant chunk.",
          "* **Answer correctness**: all key facts of the reference answer appear in the generated answer "
          "(numbers normalized); unanswerable questions count as correct only when the system refuses.",
          "* **Faithfulness**: share of answer sentences entailed (p ≥ 0.5) by the retrieved passages, judged by the "
          "NLI cross-encoder over 1–3-sentence windows of each passage (with its title/date/page header). It is a "
          "conservative lower bound: NLI models under-score facts read from table rows and sentences that combine "
          "two facts, so some correctly grounded sentences count as unsupported (see per-question results).",
          "* **Citation precision**: share of cited passages `[n]` that contain gold evidence. **Citation page "
          "accuracy**: share of cited passages whose document and page range contain a gold page.",
          "* **Latency**: measured wall-clock retrieval + generation for each query on this machine. When two "
          "configurations retrieve the identical top-5 for a question, the generation is computed once and its "
          "measured time is reused.", "",
          "## Limitations", "",
          "* The corpus is a purpose-built synthetic set of 13 enterprise documents (fictional company), written "
          "for this benchmark with exact evidence spans; absolute numbers will differ on real corpora.",
          "* Metadata filters in configuration 5 are the filters a user would set in the UI (stored per question); "
          "they are not inferred automatically from the question text.",
          "* Answer correctness uses key-fact matching, which can miss correct paraphrases of a fact."]
    path = out_dir / f"{name}.md"
    path.write_text("\n".join(L) + "\n")
    return path


if __name__ == "__main__":
    res = json.loads(Path(sys.argv[1]).read_text())
    print(write_report(res, Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/benchmarks")))
