import { useState, type FormEvent } from "react";
import { Search as SearchIcon } from "lucide-react";
import { api, DEFAULT_CONFIG, type Filters, type RetrievalConfig, type Source } from "../api";
import { DocumentPreview } from "../components/DocumentPreview";
import { RetrievalControls } from "../components/RetrievalControls";
import { SourceCard } from "../components/SourceCard";
import { ms } from "../util";

export default function Search() {
  const [query, setQuery] = useState("");
  const [config, setConfig] = useState<RetrievalConfig>(DEFAULT_CONFIG);
  const [filters, setFilters] = useState<Filters>({});
  const [results, setResults] = useState<Source[] | null>(null);
  const [timings, setTimings] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Source | null>(null);
  const [asked, setAsked] = useState("");

  const run = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.search(query, config, filters);
      setResults(r.results);
      setTimings(r.timings_ms);
      setAsked(query);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head"><div><h1>Semantic search</h1><p>Inspect what the retrieval pipeline finds, with the score from every stage.</p></div></div>
      <div className="card card-pad stack">
        <form className="row" onSubmit={run} style={{ flexWrap: "nowrap" }}>
          <input style={{ flex: 1 }} placeholder="Search across all documents…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search query" />
          <button className="btn btn-primary" disabled={busy}><SearchIcon size={15} />{busy ? "Searching…" : "Search"}</button>
        </form>
        <RetrievalControls config={config} setConfig={setConfig} filters={filters} setFilters={setFilters} />
      </div>
      {error && <div className="alert">{error}</div>}
      {results && (
        <div className="stack">
          <div className="row muted" style={{ fontSize: 12.5, gap: 16 }}>
            <span>{results.length} results</span>
            {Object.entries(timings).map(([k, v]) => <span key={k}>{k.replace("_ms", "")}: <b className="num">{ms(v)}</b></span>)}
          </div>
          {results.map((s, i) => <SourceCard key={s.chunk_id} s={s} rank={i + 1} query={asked} onOpen={setPreview} />)}
          {!results.length && <div className="card empty">No matching passages. Try removing filters.</div>}
        </div>
      )}
      {preview && <DocumentPreview documentId={preview.document_id} title={preview.title || preview.filename} focusChunkId={preview.chunk_id}
        focusPage={preview.page_start} onClose={() => setPreview(null)} />}
    </div>
  );
}
