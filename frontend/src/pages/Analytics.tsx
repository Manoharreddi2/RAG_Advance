import { Fragment, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { ago, ms, pct } from "../util";

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="card tile"><div className="label">{label}</div><div className="value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>;
}

const axis = { tickLine: false, axisLine: false, tick: { fill: "var(--text-2)", fontSize: 11 } } as const;
const tip = (fmt: (v: number) => string, name: string) => ({ active, payload, label }: any) =>
  active && payload?.length ? <div className="tooltip"><div>{label}</div>{name}: <b>{fmt(payload[0].value)}</b></div> : null;

export default function Analytics() {
  const [days, setDays] = useState(7);
  const [s, setS] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.analytics(days).then(setS).catch((e) => setError(e.message));
    api.queries(50).then(setRows).catch(() => {});
  }, [days]);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Performance analytics</h1><p>Computed from the query log: every search and chat request is recorded with timings, tokens, cost and errors.</p></div>
        <div className="seg">{[1, 7, 30].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d === 1 ? "24 h" : `${d} days`}</button>)}</div>
      </div>
      {error && <div className="alert">{error}</div>}
      {s && <>
        <div className="tiles">
          <Tile label="Queries" value={String(s.queries)} sub={Object.entries(s.by_endpoint).map(([k, v]) => `${k} ${v}`).join(" · ")} />
          <Tile label="Latency p50" value={ms(s.latency_ms.p50)} sub={`p95 ${ms(s.latency_ms.p95)}`} />
          <Tile label="Avg retrieval / generation" value={ms(s.latency_ms.retrieval_avg)} sub={`generation ${ms(s.latency_ms.generation_avg)}`} />
          <Tile label="Cache hit rate" value={pct(s.cache_hit_rate)} sub="Redis answer cache" />
          <Tile label="Tokens" value={(s.tokens.prompt + s.tokens.completion).toLocaleString()} sub={`${s.tokens.prompt.toLocaleString()} in · ${s.tokens.completion.toLocaleString()} out`} />
          <Tile label="LLM cost" value={`$${s.cost_usd.toFixed(4)}`} sub="at configured token prices" />
          <Tile label="Abstention rate" value={pct(s.abstention_rate)} sub="answers with insufficient evidence" />
          <Tile label="Errors" value={String(s.errors)} sub={`${s.documents.chunks.toLocaleString()} chunks indexed`} />
        </div>
        <div className="grid-2">
          <div className="card chart-card"><h3>Queries per day</h3><div className="sub">All endpoints</div>
            <ResponsiveContainer width="100%" height={200}><BarChart data={s.series} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="day" {...axis} /><YAxis allowDecimals={false} {...axis} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} content={tip((v) => String(v), "Queries")} />
              <Bar dataKey="queries" fill="var(--accent)" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
            </BarChart></ResponsiveContainer></div>
          <div className="card chart-card"><h3>p95 latency per day</h3><div className="sub">End-to-end request time</div>
            <ResponsiveContainer width="100%" height={200}><LineChart data={s.series} margin={{ top: 8, right: 12, left: -4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" /><XAxis dataKey="day" {...axis} /><YAxis {...axis} tickFormatter={(v) => ms(v)} />
              <Tooltip content={tip(ms, "p95")} />
              <Line dataKey="p95_ms" stroke="var(--accent)" strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
            </LineChart></ResponsiveContainer></div>
        </div>
      </>}
      <div className="card">
        <div className="card-head"><h2>Recent queries</h2><span className="faint" style={{ fontSize: 12 }}>Click a row for the retrieved chunks</span></div>
        <div className="table-wrap"><table>
          <thead><tr><th>When</th><th>Endpoint</th><th>Query</th><th className="r">Total</th><th className="r">Retrieval</th><th className="r">Generation</th><th className="r">Tokens</th><th>Flags</th></tr></thead>
          <tbody>{rows.map((r) => (
            <Fragment key={r.id}>
              <tr style={{ cursor: "pointer" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                <td className="faint">{ago(r.created_at)}</td><td><span className="badge">{r.endpoint}</span></td>
                <td style={{ maxWidth: 380 }}>{r.query}{r.standalone_query && r.standalone_query !== r.query && <div className="faint" style={{ fontSize: 12 }}>↳ {r.standalone_query}</div>}</td>
                <td className="r">{ms(r.total_ms)}</td><td className="r">{ms(r.retrieval_ms)}</td><td className="r">{ms(r.generation_ms)}</td>
                <td className="r">{r.prompt_tokens + r.completion_tokens || "–"}</td>
                <td><div className="row" style={{ gap: 4 }}>{r.cache_hit && <span className="badge info">cache</span>}{r.abstained && <span className="badge warn">abstained</span>}{r.error && <span className="badge bad" title={r.error}>error</span>}</div></td>
              </tr>
              {open === r.id && <tr><td colSpan={8} style={{ background: "var(--surface-2)" }}>
                <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>config: {JSON.stringify(r.config)} · filters: {JSON.stringify(r.filters)}{r.model ? ` · model: ${r.model}` : ""}</div>
                <table><thead><tr><th>#</th><th>Document</th><th className="r">Page</th><th className="r">Final score</th><th>Stage scores</th></tr></thead>
                  <tbody>{r.retrieved.map((c: any) => <tr key={c.chunk_id}><td>{c.rank}</td><td>{c.filename}</td><td className="r">{c.page_start ?? "–"}</td><td className="r">{c.score?.toFixed(4)}</td>
                    <td className="mono faint">{Object.entries(c.scores ?? {}).map(([k, v]) => `${k}=${(v as number).toFixed(3)}`).join("  ")}</td></tr>)}</tbody></table>
                {r.error && <div className="alert" style={{ marginTop: 8 }}>{r.error}</div>}
              </td></tr>}
            </Fragment>))}
            {!rows.length && <tr><td colSpan={8}><div className="empty">No queries logged yet.</div></td></tr>}
          </tbody>
        </table></div>
      </div>
    </div>
  );
}
