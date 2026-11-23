import { useState } from "react";
import { FileText } from "lucide-react";
import type { Source } from "../api";
import { highlight, pages } from "../util";

export function SourceCard({ s, rank, query, onOpen }: { s: Source; rank: number; query?: string; onOpen: (s: Source) => void }) {
  const [open, setOpen] = useState(false);
  const fmt = (v?: number) => (v === undefined ? null : Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2));
  return (
    <div className={`source ${open ? "expanded" : ""}`}>
      <div className="meta">
        <span className="badge info">#{rank}</span>
        <button className="btn btn-ghost btn-sm" style={{ padding: 0, color: "var(--text)", fontWeight: 600 }} onClick={() => onOpen(s)}>
          <FileText size={14} />{s.title || s.filename}
        </button>
        <span>{pages(s.page_start, s.page_end)}</span>
        {s.section && <span className="faint">· {s.section.split(" > ").slice(-1)[0]}</span>}
        {s.chunk_type === "table" && <span className="badge">table</span>}
        {s.category && <span className="badge">{s.category}</span>}
        {s.doc_date && <span className="faint">{s.doc_date}</span>}
      </div>
      <div className="text">{query ? highlight(s.text, query) : s.text}</div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="scorebar">
          {fmt(s.scores.rerank) !== null && <span>rerank <b>{fmt(s.scores.rerank)}</b></span>}
          {fmt(s.scores.rrf) !== null && <span>RRF <b>{fmt(s.scores.rrf)}</b></span>}
          {fmt(s.scores.dense) !== null && <span>vector <b>{fmt(s.scores.dense)}</b>{s.ranks.dense ? ` (#${s.ranks.dense})` : ""}</span>}
          {fmt(s.scores.bm25) !== null && <span>BM25 <b>{fmt(s.scores.bm25)}</b>{s.ranks.bm25 ? ` (#${s.ranks.bm25})` : ""}</span>}
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>{open ? "Less" : "More"}</button>
      </div>
    </div>
  );
}
