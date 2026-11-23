import { useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { MetricBars, type BarDatum } from "../components/MetricBars";
import { fix, ms, pct } from "../util";

type Subset = "overall" | "with_filters" | "without_filters";
const RETRIEVAL: [string, string, boolean, (v: number) => string][] = [
  ["recall@1", "Recall@1", true, (v) => v.toFixed(3)], ["recall@5", "Recall@5", true, (v) => v.toFixed(3)],
  ["precision@5", "Precision@5", true, (v) => v.toFixed(3)], ["mrr", "Mean Reciprocal Rank", true, (v) => v.toFixed(3)],
  ["top1_doc_correct", "Top-1 from correct document", true, (v) => pct(v, 0)], ["retrieval_ms_p50", "Retrieval latency p50", false, (v) => ms(v)],
];
const ANSWER: [string, string, boolean, (v: number) => string][] = [
  ["answer_correctness", "Answer correctness", true, (v) => pct(v, 0)], ["faithfulness", "Faithfulness (NLI)", true, (v) => pct(v, 0)],
  ["citation_precision", "Citation precision", true, (v) => pct(v, 0)], ["citation_page_accuracy", "Citation page accuracy", true, (v) => pct(v, 0)],
  ["unanswerable_abstention_rate", "Correct refusals (unanswerable)", true, (v) => pct(v, 0)], ["latency_ms_p50", "End-to-end latency p50", false, (v) => ms(v)],
  ["projected_cost_per_query_usd", "Projected API cost / query", false, (v) => `$${v.toFixed(5)}`],
];

export default function Evaluation() {
  const { can } = useAuth();
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [run, setRun] = useState<any>(null);
  const [subset, setSubset] = useState<Subset>("overall");
  const [qConfig, setQConfig] = useState("");
  const [qFilter, setQFilter] = useState<"all" | "wrong" | "miss">("all");
  const [msg, setMsg] = useState<string | null>(null);

  const loadRuns = () => api.evalRuns().then((r) => { setRuns(r); if (r.length && !runId) setRunId(r[0].id); });
  useEffect(() => { loadRuns(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (runId) api.evalRun(runId).then((r) => { setRun(r); setQConfig(Object.keys(r.metrics).slice(-1)[0]); }); }, [runId]);

  const configs = run ? Object.entries<any>(run.metrics) : [];
  const env = run?.environment ?? {};
  const series = (key: string): BarDatum[] => configs.map(([k, v]) => ({ key: k, short: v.label.split(". ")[0], label: v.label, value: v[subset][key] ?? null }));
  const hasGen = !!env.generation;
  const questions = useMemo(() => (run?.per_question ?? []).filter((q: any) => q.config === qConfig).filter((q: any) =>
    qFilter === "all" ? true : qFilter === "wrong" ? q.correct === 0 : q.answerable && (q["recall@5"] ?? 1) < 1), [run, qConfig, qFilter]);

  if (!runs.length) return (
    <div className="page">
      <div className="page-head"><div><h1>Evaluation</h1><p>Benchmark results produced by <code>python -m eval.run</code>.</p></div></div>
      <div className="card empty stack" style={{ alignItems: "center" }}>
        <p>No evaluation runs imported yet.</p>
        {can("admin") && <button className="btn btn-primary" onClick={() => api.importEval().then((r) => { setMsg(`Imported ${r.imported} run(s)`); loadRuns(); })}><Download size={15} />Import results</button>}
        {msg && <p className="muted">{msg}</p>}
      </div>
    </div>
  );

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Evaluation</h1><p>Five retrieval configurations measured on {env.n_questions} questions ({env.n_answerable} answerable, {env.n_with_filters} with metadata filters). Numbers come straight from the run file.</p></div>
        <div className="row">
          <select value={runId} onChange={(e) => setRunId(e.target.value)} aria-label="Evaluation run">{runs.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>
          {can("admin") && <button className="btn" onClick={() => api.importEval().then(loadRuns)}><Download size={15} />Import</button>}
        </div>
      </div>
      {run && <>
        <div className="card card-pad row muted" style={{ fontSize: 12.5, gap: 18 }}>
          <span>Embeddings <b>{env.embedding_model}</b></span><span>Reranker <b>{env.reranker_model}</b></span>
          <span>LLM <b>{env.llm ?? "— (retrieval only)"}</b></span><span>NLI <b>{env.nli_model}</b></span>
          {Object.entries<any>(env.index ?? {}).map(([k, v]) => <span key={k}>{k} chunks <b>{v.chunks}</b> (avg {v.avg_tokens} tok)</span>)}
          <span>{env.cpu_count} CPU cores · {env.device}</span>
        </div>
        <div className="row">
          <div className="seg">{(["overall", "with_filters", "without_filters"] as Subset[]).map((s) => (
            <button key={s} className={subset === s ? "on" : ""} onClick={() => setSubset(s)}>
              {s === "overall" ? "All questions" : s === "with_filters" ? `With filters (n=${configs[0]?.[1].with_filters.n})` : "Without filters"}</button>))}</div>
          <span className="faint" style={{ fontSize: 12 }}>1 = basic vector · 2 = improved chunking · 3 = hybrid RRF · 4 = + rerank · 5 = + filters</span>
        </div>
        <h2>Retrieval quality</h2>
        <div className="chart-grid">{RETRIEVAL.map(([k, t, hb, f]) => <MetricBars key={k} title={t} data={series(k)} higherBetter={hb} format={f} />)}</div>
        {hasGen && <><h2>Answer quality, latency and cost</h2>
          <div className="chart-grid">{ANSWER.map(([k, t, hb, f]) => <MetricBars key={k} title={t} data={series(k)} higherBetter={hb} format={f}
            sub={k === "projected_cost_per_query_usd" ? "Measured tokens × configured API price" : undefined} />)}</div></>}

        <div className="card table-wrap">
          <div className="card-head"><h2>All metrics</h2><span className="faint" style={{ fontSize: 12 }}>95% bootstrap confidence intervals in brackets</span></div>
          <table>
            <thead><tr><th>Configuration</th><th className="r">R@1</th><th className="r">R@3</th><th className="r">R@5</th><th className="r">R@10</th><th className="r">P@5</th><th className="r">MRR</th>
              {hasGen && <><th className="r">Correct</th><th className="r">Faithful</th><th className="r">Cite prec.</th><th className="r">Cite page</th><th className="r">Refusals ✓</th><th className="r">False refusals</th><th className="r">p50</th><th className="r">p95</th><th className="r">Tokens in/out</th></>}</tr></thead>
            <tbody>{configs.map(([k, v]) => { const o = v[subset]; return (
              <tr key={k}><td>{v.label}</td><td className="r">{fix(o["recall@1"])}</td><td className="r">{fix(o["recall@3"])}</td>
                <td className="r">{fix(o["recall@5"])}{o["recall@5_ci95"] && <div className="faint">[{o["recall@5_ci95"].map((x: number) => x.toFixed(2)).join("–")}]</div>}</td>
                <td className="r">{fix(o["recall@10"])}</td><td className="r">{fix(o["precision@5"])}</td>
                <td className="r">{fix(o.mrr)}{o.mrr_ci95 && <div className="faint">[{o.mrr_ci95.map((x: number) => x.toFixed(2)).join("–")}]</div>}</td>
                {hasGen && <><td className="r">{pct(o.answer_correctness)}{o.answer_correctness_ci95 && <div className="faint">[{o.answer_correctness_ci95.map((x: number) => (x * 100).toFixed(0)).join("–")}%]</div>}</td>
                  <td className="r">{pct(o.faithfulness)}</td><td className="r">{pct(o.citation_precision)}</td><td className="r">{pct(o.citation_page_accuracy)}</td>
                  <td className="r">{pct(o.unanswerable_abstention_rate, 0)}</td><td className="r">{pct(o.false_abstention_rate)}</td>
                  <td className="r">{ms(o.latency_ms_p50)}</td><td className="r">{ms(o.latency_ms_p95)}</td><td className="r">{Math.round(o.prompt_tokens_mean ?? 0)} / {Math.round(o.completion_tokens_mean ?? 0)}</td></>}
              </tr>); })}</tbody>
          </table>
        </div>

        <div className="card">
          <div className="card-head"><h2>Per-question results</h2>
            <div className="row">
              <select value={qConfig} onChange={(e) => setQConfig(e.target.value)} aria-label="Configuration">{configs.map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
              <div className="seg"><button className={qFilter === "all" ? "on" : ""} onClick={() => setQFilter("all")}>All</button>
                {hasGen && <button className={qFilter === "wrong" ? "on" : ""} onClick={() => setQFilter("wrong")}>Incorrect answers</button>}
                <button className={qFilter === "miss" ? "on" : ""} onClick={() => setQFilter("miss")}>Retrieval misses</button></div>
            </div>
          </div>
          <div className="table-wrap" style={{ maxHeight: 560, overflow: "auto" }}>
            <table>
              <thead><tr><th>ID</th><th>Type</th><th>Query</th><th className="r">MRR</th><th className="r">R@5</th>{hasGen && <><th>Answer</th><th className="r">Correct</th><th className="r">Faithful</th></>}</tr></thead>
              <tbody>{questions.map((q: any) => (
                <tr key={q.id}><td className="mono">{q.id}</td><td><span className="badge">{q.type}</span>{q.has_filters && <span className="badge info" style={{ marginLeft: 4 }}>filter</span>}</td>
                  <td style={{ maxWidth: 320 }}>{q.query}</td><td className="r">{q.mrr === undefined ? "–" : q.mrr.toFixed(2)}</td><td className="r">{q["recall@5"] === undefined ? "–" : q["recall@5"].toFixed(2)}</td>
                  {hasGen && <><td style={{ maxWidth: 420, fontSize: 12.5 }}>{q.answer}</td>
                    <td className="r"><span className={`badge ${q.correct ? "good" : "bad"}`}>{q.correct ? "yes" : "no"}</span></td><td className="r">{pct(q.faithfulness, 0)}</td></>}
                </tr>))}</tbody>
            </table>
          </div>
        </div>
      </>}
    </div>
  );
}
