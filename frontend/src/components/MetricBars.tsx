import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface BarDatum { key: string; short: string; label: string; value: number | null }

/** One metric across configurations: single hue, best value emphasized, value labels, hover tooltip. */
export function MetricBars({ title, sub, data, higherBetter = true, format }: {
  title: string; sub?: string; data: BarDatum[]; higherBetter?: boolean; format: (v: number) => string;
}) {
  const vals = data.map((d) => d.value).filter((v): v is number => v !== null);
  const best = vals.length ? (higherBetter ? Math.max(...vals) : Math.min(...vals)) : null;
  return (
    <div className="card chart-card">
      <h3>{title}</h3>
      <div className="sub">{sub ?? (higherBetter ? "Higher is better" : "Lower is better")}</div>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={data} margin={{ top: 18, right: 4, left: 4, bottom: 0 }}>
          <XAxis dataKey="short" tickLine={false} axisLine={{ stroke: "var(--border)" }} tick={{ fill: "var(--text-2)", fontSize: 12 }} />
          <YAxis hide domain={[0, (max: number) => (max > 0 ? max * 1.15 : 1)]} />
          <Tooltip cursor={{ fill: "var(--surface-2)" }} content={({ active, payload }) => active && payload?.length ? (
            <div className="tooltip"><div>{(payload[0].payload as BarDatum).label}</div><b>{payload[0].value === null ? "–" : format(payload[0].value as number)}</b></div>) : null} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={38} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.key} fill={d.value === best ? "var(--accent)" : "var(--bar)"} />)}
            <LabelList dataKey="value" position="top" formatter={(v: number | null) => (v === null ? "" : format(v))} style={{ fill: "var(--text)", fontSize: 11 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
