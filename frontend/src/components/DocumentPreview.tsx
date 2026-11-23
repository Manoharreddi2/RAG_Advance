import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api, type Chunk } from "../api";
import { pages } from "../util";

/** Side drawer: parsed chunks (with pages/sections) and, for PDFs, the original file. */
export function DocumentPreview({ documentId, title, focusChunkId, focusPage, onClose }: {
  documentId: string; title: string; focusChunkId?: string; focusPage?: number | null; onClose: () => void;
}) {
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"chunks" | "original">("chunks");
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [mime, setMime] = useState<string>("");
  const [text, setText] = useState<string | null>(null);
  const focusRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.chunks(documentId).then(setChunks).catch((e) => setError(e.message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [documentId, onClose]);

  useEffect(() => { focusRef.current?.scrollIntoView({ block: "center" }); }, [chunks]);

  useEffect(() => {
    if (view !== "original" || fileUrl) return;
    api.fileBlob(documentId).then(async (b) => {
      setMime(b.type);
      if (b.type.startsWith("text/")) setText(await b.text());
      setFileUrl(URL.createObjectURL(b));
    }).catch((e) => setError(e.message));
  }, [view, documentId, fileUrl]);
  useEffect(() => () => { if (fileUrl) URL.revokeObjectURL(fileUrl); }, [fileUrl]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" role="dialog" aria-label={`Preview of ${title}`} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>{title}</h2>
            <div className="faint" style={{ fontSize: 12.5 }}>{chunks ? `${chunks.length} chunks` : "Loading…"}{focusPage ? ` · cited page ${focusPage}` : ""}</div>
          </div>
          <div className="row">
            <div className="seg">
              <button className={view === "chunks" ? "on" : ""} onClick={() => setView("chunks")}>Parsed chunks</button>
              <button className={view === "original" ? "on" : ""} onClick={() => setView("original")}>Original</button>
            </div>
            <button className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button>
          </div>
        </div>
        <div className="drawer-body">
          {error && <div className="alert">{error}</div>}
          {view === "chunks" && chunks?.map((c) => {
            const hl = c.id === focusChunkId;
            return (
              <div key={c.id} ref={hl ? focusRef : undefined} className={`chunk ${hl ? "hl" : ""}`}>
                <div className="meta">#{c.chunk_index} · {pages(c.page_start, c.page_end)} · {c.section_path || "—"} · {c.token_count} tokens{c.chunk_type === "table" ? " · table" : ""}</div>
                {c.text}
              </div>
            );
          })}
          {view === "original" && fileUrl && (mime === "application/pdf"
            ? <iframe className="pdf-frame" title="Original document" src={`${fileUrl}#page=${focusPage ?? 1}`} />
            : text !== null ? <pre className="chunk" style={{ margin: 0 }}>{text}</pre>
            : <div className="empty">This format cannot be rendered in the browser. <a href={fileUrl} download>Download the original</a>.</div>)}
        </div>
      </div>
    </div>
  );
}
