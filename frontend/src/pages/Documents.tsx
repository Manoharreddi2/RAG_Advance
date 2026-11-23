import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, RefreshCw, Trash2, Upload } from "lucide-react";
import { api, type Doc } from "../api";
import { useAuth } from "../auth";
import { DocumentPreview } from "../components/DocumentPreview";
import { ago, bytes } from "../util";

const STATUS: Record<string, string> = { ready: "good", processing: "info", pending: "warn", failed: "bad" };

export default function Documents() {
  const { can } = useAuth();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ filename: string; status: string; detail: string | null }[] | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState({ category: "", author: "", doc_date: "", tags: "" });
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<Doc | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    const params: Record<string, string> = { page_size: "200" };
    if (q) params.q = q;
    if (category) params.category = category;
    api.documents(params).then((r) => { setDocs(r.items); setTotal(r.total); }).catch((e) => setError(e.message));
  }, [q, category]);
  useEffect(load, [load]);
  // poll while anything is being processed (asynchronous ingestion)
  useEffect(() => {
    if (!docs.some((d) => d.status === "pending" || d.status === "processing")) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [docs, load]);

  const upload = async () => {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    Object.entries(meta).forEach(([k, v]) => v && form.append(k, v));
    try {
      setResults(await api.upload(form));
      setFiles([]);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const categories = [...new Set(docs.map((d) => d.category).filter(Boolean))] as string[];
  const counts = docs.reduce<Record<string, number>>((a, d) => ({ ...a, [d.status]: (a[d.status] ?? 0) + 1 }), {});

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Documents</h1><p>{total} documents · {docs.reduce((a, d) => a + d.chunk_count, 0)} indexed chunks{counts.processing || counts.pending ? ` · ${(counts.processing ?? 0) + (counts.pending ?? 0)} processing` : ""}</p></div>
        <div className="row">
          <input placeholder="Filter by name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter documents by name" />
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
            <option value="">All categories</option>{categories.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}

      {can("editor") && (
        <div className="card card-pad stack">
          <h2>Upload documents</h2>
          <div className={`dropzone ${over ? "over" : ""}`} onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); setFiles([...files, ...Array.from(e.dataTransfer.files)]); }}>
            <Upload size={20} /><div style={{ marginTop: 6 }}>Drop PDF, DOCX, TXT or Markdown files here, or click to choose. Batch uploads are supported.</div>
            <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.txt,.md,.markdown"
              onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
          </div>
          {files.length > 0 && <div className="row">{files.map((f, i) => (
            <span key={i} className="badge">{f.name} · {bytes(f.size)} <button className="icon-btn" style={{ padding: 0 }} aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>×</button></span>))}
          </div>}
          <div className="filters">
            <label className="field">Category<input value={meta.category} onChange={(e) => setMeta({ ...meta, category: e.target.value })} placeholder="e.g. Finance" /></label>
            <label className="field">Author<input value={meta.author} onChange={(e) => setMeta({ ...meta, author: e.target.value })} placeholder="from file if empty" /></label>
            <label className="field">Document date<input type="date" value={meta.doc_date} onChange={(e) => setMeta({ ...meta, doc_date: e.target.value })} /></label>
            <label className="field">Tags<input value={meta.tags} onChange={(e) => setMeta({ ...meta, tags: e.target.value })} placeholder="comma separated" /></label>
            <button className="btn btn-primary" disabled={!files.length || busy} onClick={upload}><Upload size={15} />{busy ? "Uploading…" : `Upload ${files.length || ""}`}</button>
          </div>
          {results && <div className="row">{results.map((r) => (
            <span key={r.filename} className={`badge ${r.status === "created" || r.status === "updated" ? "good" : r.status === "duplicate" ? "warn" : "bad"}`} title={r.detail ?? ""}>
              {r.filename}: {r.status}{r.detail ? ` — ${r.detail}` : ""}</span>))}</div>}
        </div>
      )}

      <div className="card table-wrap">
        <table>
          <thead><tr><th>Document</th><th>Category</th><th>Author</th><th>Date</th><th>Status</th><th className="r">Pages</th><th className="r">Chunks</th><th className="r">Version</th><th>Updated</th><th /></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td><div style={{ fontWeight: 600 }}>{d.title || d.filename}</div><div className="faint mono" style={{ fontSize: 11.5 }}>{d.filename} · {bytes(d.size_bytes)}</div></td>
                <td>{d.category ?? "—"}</td><td>{d.author ?? "—"}</td><td className="num">{d.doc_date ?? "—"}</td>
                <td><span className={`badge ${STATUS[d.status] ?? ""}`} title={d.error ?? ""}>{d.status}</span>{d.error && <div className="faint" style={{ fontSize: 11.5, maxWidth: 220 }}>{d.error}</div>}</td>
                <td className="r">{d.page_count ?? "—"}</td><td className="r">{d.chunk_count}</td><td className="r">v{d.version}</td>
                <td className="faint">{ago(d.updated_at)}</td>
                <td><div className="row" style={{ gap: 2, flexWrap: "nowrap" }}>
                  <button className="icon-btn" title="Preview" aria-label={`Preview ${d.filename}`} onClick={() => setPreview(d)}><Eye size={16} /></button>
                  {can("editor") && <>
                    <button className="icon-btn" title="Re-index" aria-label={`Re-index ${d.filename}`} onClick={() => api.reindex(d.id).then(load)}><RefreshCw size={16} /></button>
                    <button className="icon-btn btn-danger" title="Delete" aria-label={`Delete ${d.filename}`} onClick={() => confirm(`Delete ${d.filename}? Its vectors and chunks are removed.`) && api.deleteDoc(d.id).then(load)}><Trash2 size={16} /></button>
                  </>}
                </div></td>
              </tr>
            ))}
            {!docs.length && <tr><td colSpan={10}><div className="empty">No documents yet.{can("editor") ? " Upload some above." : ""}</div></td></tr>}
          </tbody>
        </table>
      </div>
      {preview && <DocumentPreview documentId={preview.id} title={preview.title || preview.filename} onClose={() => setPreview(null)} />}
    </div>
  );
}
