import { useEffect, useState } from "react";
import { api, type Facets, type Filters, type RetrievalConfig } from "../api";

/** Metadata filters + retrieval pipeline configuration (shared by Search and Chat). */
export function RetrievalControls({ config, setConfig, filters, setFilters, compact = false }: {
  config: RetrievalConfig; setConfig: (c: RetrievalConfig) => void;
  filters: Filters; setFilters: (f: Filters) => void; compact?: boolean;
}) {
  const [facets, setFacets] = useState<Facets | null>(null);
  useEffect(() => { api.facets().then(setFacets).catch(() => setFacets(null)); }, []);
  const single = (v: string) => (v ? [v] : []);

  return (
    <div className="stack">
      <div className="filters">
        <label className="field">Document
          <select value={filters.filenames?.[0] ?? ""} onChange={(e) => setFilters({ ...filters, filenames: single(e.target.value) })}>
            <option value="">All documents</option>
            {facets?.filenames.map((f) => <option key={f}>{f}</option>)}
          </select>
        </label>
        <label className="field">Category
          <select value={filters.categories?.[0] ?? ""} onChange={(e) => setFilters({ ...filters, categories: single(e.target.value) })}>
            <option value="">All categories</option>
            {facets?.categories.map((f) => <option key={f}>{f}</option>)}
          </select>
        </label>
        <label className="field">Author
          <select value={filters.authors?.[0] ?? ""} onChange={(e) => setFilters({ ...filters, authors: single(e.target.value) })}>
            <option value="">All authors</option>
            {facets?.authors.map((f) => <option key={f}>{f}</option>)}
          </select>
        </label>
        <label className="field">Dated from
          <input type="date" value={filters.date_from ?? ""} onChange={(e) => setFilters({ ...filters, date_from: e.target.value || null })} />
        </label>
        <label className="field">Dated to
          <input type="date" value={filters.date_to ?? ""} onChange={(e) => setFilters({ ...filters, date_to: e.target.value || null })} />
        </label>
      </div>
      {!compact && (
        <div className="row" style={{ gap: 18 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="muted" style={{ fontSize: 12.5, fontWeight: 500 }}>Retrieval</span>
            <div className="seg" role="group" aria-label="Retrieval mode">
              {(["dense", "bm25", "hybrid"] as const).map((m) => (
                <button key={m} className={config.mode === m ? "on" : ""} onClick={() => setConfig({ ...config, mode: m })}>
                  {m === "dense" ? "Vector" : m === "bm25" ? "BM25" : "Hybrid (RRF)"}
                </button>
              ))}
            </div>
          </div>
          <label className="check"><input type="checkbox" checked={config.rerank} onChange={(e) => setConfig({ ...config, rerank: e.target.checked })} />Cross-encoder rerank</label>
          <label className="check"><input type="checkbox" checked={config.use_filters} onChange={(e) => setConfig({ ...config, use_filters: e.target.checked })} />Apply filters</label>
          <label className="check">Top-k
            <input type="number" min={1} max={20} value={config.top_k} style={{ width: 64 }}
              onChange={(e) => setConfig({ ...config, top_k: Math.max(1, Math.min(20, +e.target.value || 5)) })} />
          </label>
          <label className="check">Candidates
            <input type="number" min={5} max={100} value={config.candidates} style={{ width: 70 }}
              onChange={(e) => setConfig({ ...config, candidates: Math.max(5, Math.min(100, +e.target.value || 30)) })} />
          </label>
        </div>
      )}
    </div>
  );
}
