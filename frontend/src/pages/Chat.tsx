import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, MessageSquarePlus, Send, SlidersHorizontal, Square, Trash2 } from "lucide-react";
import { api, DEFAULT_CONFIG, streamChat, type Citation, type Filters, type RetrievalConfig, type Source } from "../api";
import { DocumentPreview } from "../components/DocumentPreview";
import { RetrievalControls } from "../components/RetrievalControls";
import { ms, pages } from "../util";

interface Msg {
  role: "user" | "assistant"; content: string; citations?: Citation[]; sources?: Source[]; streaming?: boolean;
  abstained?: boolean; quotes?: { quote: string; verified: boolean }[]; trace?: Record<string, any>; error?: string;
}
type Preview = { documentId: string; title: string; chunkId?: string; page?: number | null };

const SUGGESTIONS = ["What is the hotel cap for Tier 1 cities?", "How does the 401(k) match work?",
  "What should on-call do for error HX-1201?", "Who approves a 120,000 USD purchase?"];

function renderAnswer(text: string, sources: Source[] | undefined, open: (n: number) => void): ReactNode {
  return text.split(/(\[\d+(?:\s*,\s*\d+)*\])/g).map((part, i) => {
    const m = part.match(/^\[(.+)\]$/);
    if (!m) return <Fragment key={i}>{part}</Fragment>;
    return <Fragment key={i}>{m[1].split(/\s*,\s*/).map((n) => {
      const idx = +n;
      const s = sources?.[idx - 1];
      return <button key={n} className="cite" title={s ? `${s.title || s.filename} ${pages(s.page_start, s.page_end)}` : `Source ${n}`} onClick={() => open(idx)}>{n}</button>;
    })}</Fragment>;
  });
}

export default function Chat() {
  const [convs, setConvs] = useState<{ id: string; title: string; updated_at: string }[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [config, setConfig] = useState<RetrievalConfig>(DEFAULT_CONFIG);
  const [filters, setFilters] = useState<Filters>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvs = () => api.conversations().then(setConvs).catch(() => {});
  useEffect(() => { loadConvs(); }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  const openConv = async (id: string) => {
    abort.current?.abort();
    const c = await api.conversation(id);
    setConvId(id);
    setMsgs(c.messages.map((m) => ({ role: m.role as Msg["role"], content: m.content, citations: m.citations })));
  };

  const patchLast = (fn: (m: Msg) => Msg) => setMsgs((ms) => [...ms.slice(0, -1), fn(ms[ms.length - 1])]);

  const send = async (e?: FormEvent, text?: string) => {
    e?.preventDefault();
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: message }, { role: "assistant", content: "", streaming: true }]);
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      await streamChat({ message, conversation_id: convId, config, filters }, (ev) => {
        if (ev.type === "conversation") setConvId(ev.conversation_id);
        else if (ev.type === "sources") patchLast((m) => ({ ...m, sources: ev.chunks }));
        else if (ev.type === "rewrite") patchLast((m) => ({ ...m, trace: { ...m.trace, standalone: ev.standalone_query } }));
        else if (ev.type === "token") patchLast((m) => ({ ...m, content: m.content + ev.text }));
        else if (ev.type === "error") patchLast((m) => ({ ...m, error: ev.detail, streaming: false }));
        else if (ev.type === "done") patchLast((m) => ({
          ...m, content: ev.answer, citations: ev.citations, abstained: ev.abstained, quotes: ev.quotes, streaming: false,
          trace: { ...m.trace, ...ev.timings_ms, ...ev.usage, model: ev.model, cache_hit: ev.cache_hit },
        }));
      }, ctrl.signal);
    } catch (err: any) {
      if (err.name !== "AbortError") patchLast((m) => ({ ...m, error: err.message }));
    } finally {
      patchLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
      loadConvs();
    }
  };

  const openSource = (m: Msg, n: number) => {
    const s = m.sources?.[n - 1];
    const c = m.citations?.find((x) => x.index === n);
    if (s) setPreview({ documentId: s.document_id, title: s.title || s.filename, chunkId: s.chunk_id, page: s.page_start });
    else if (c) setPreview({ documentId: c.document_id, title: c.title || c.filename, chunkId: c.chunk_id, page: c.page_start });
  };
  const activeFilters = Object.values(filters).filter((v) => (Array.isArray(v) ? v.length : v)).length;

  return (
    <div className="chat">
      <div className="conv-list">
        <button className="btn" style={{ justifyContent: "center", marginBottom: 8 }} onClick={() => { abort.current?.abort(); setConvId(null); setMsgs([]); }}>
          <MessageSquarePlus size={15} />New conversation</button>
        <div className="faint" style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px" }}>HISTORY</div>
        {convs.map((c) => (
          <div key={c.id} className={`conv-item ${c.id === convId ? "on" : ""}`} onClick={() => openConv(c.id)}>
            <span title={c.title}>{c.title}</span>
            <button className="icon-btn" style={{ padding: 2 }} aria-label="Delete conversation" onClick={(e) => {
              e.stopPropagation();
              api.deleteConversation(c.id).then(() => { if (c.id === convId) { setConvId(null); setMsgs([]); } loadConvs(); });
            }}><Trash2 size={13} /></button>
          </div>
        ))}
        {!convs.length && <div className="faint" style={{ padding: 10, fontSize: 12.5 }}>No conversations yet.</div>}
      </div>

      <div className="chat-main">
        <div className="messages">
          {!msgs.length && (
            <div className="msg" style={{ flexDirection: "column", alignItems: "center", textAlign: "center", marginTop: "8vh", gap: 10 }}>
              <h1>Ask your documents</h1>
              <p className="muted">Answers are generated only from your indexed documents, with citations to the exact page. If the documents don't contain the answer, the assistant says so.</p>
              <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
                {SUGGESTIONS.map((s) => <button key={s} className="btn btn-sm" onClick={() => send(undefined, s)}>{s}</button>)}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="bubble">
                {m.role === "user" ? m.content : (
                  <>
                    {m.abstained && <div className="badge warn" style={{ marginBottom: 6 }}><AlertTriangle size={12} />Insufficient evidence</div>}
                    <div className={`answer ${m.streaming ? "typing" : ""}`}>{m.content ? renderAnswer(m.content, m.sources, (n) => openSource(m, n)) : m.streaming ? <span className="faint">Retrieving…</span> : null}</div>
                    {m.error && <div className="alert" style={{ marginTop: 8 }}>{m.error}</div>}
                    {m.quotes?.some((q) => !q.verified) && <div className="badge bad" style={{ marginTop: 6 }}>A quoted passage could not be verified against the sources</div>}
                    {!!m.citations?.length && (
                      <div className="citations">
                        {m.citations.map((c) => (
                          <div key={c.index} className="citation" onClick={() => openSource(m, c.index)}>
                            <b>[{c.index}] {c.title || c.filename}</b> <span className="faint">{pages(c.page_start, c.page_end)}{c.section ? ` · ${c.section.split(" > ").slice(-1)[0]}` : ""}</span>
                            <div><q>{c.quote}</q></div>
                          </div>
                        ))}
                      </div>
                    )}
                    {m.trace && !m.streaming && (
                      <div className="trace num">
                        {m.trace.cache_hit && <span className="badge info">cached</span>}
                        {m.trace.standalone && <span title="Follow-up rewritten for retrieval">↳ “{m.trace.standalone}”</span>}
                        {m.trace.retrieval_ms !== undefined && <span>retrieval {ms(m.trace.retrieval_ms)}</span>}
                        {m.trace.generation_ms !== undefined && <span>generation {ms(m.trace.generation_ms)}</span>}
                        {m.trace.request_total_ms !== undefined && <span>total {ms(m.trace.request_total_ms)}</span>}
                        {m.trace.prompt_tokens !== undefined && <span>{m.trace.prompt_tokens} + {m.trace.completion_tokens} tokens</span>}
                        {m.trace.cost_usd !== undefined && <span>${Number(m.trace.cost_usd).toFixed(5)}</span>}
                        {m.trace.model && <span>{m.trace.model}</span>}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={bottom} />
        </div>
        <div className="composer">
          {showSettings && <div className="chat-settings card card-pad"><RetrievalControls config={config} setConfig={setConfig} filters={filters} setFilters={setFilters} /></div>}
          <form onSubmit={send}>
            <button type="button" className={`btn ${activeFilters ? "btn-primary" : ""}`} title="Filters and retrieval settings" aria-label="Filters and retrieval settings" onClick={() => setShowSettings(!showSettings)}>
              <SlidersHorizontal size={15} />{activeFilters || ""}</button>
            <textarea rows={1} placeholder="Ask a question about your documents…" value={input} aria-label="Message"
              onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            {busy
              ? <button type="button" className="btn" onClick={() => abort.current?.abort()} aria-label="Stop"><Square size={15} />Stop</button>
              : <button className="btn btn-primary" disabled={!input.trim()} aria-label="Send"><Send size={15} />Send</button>}
          </form>
        </div>
      </div>
      {preview && <DocumentPreview documentId={preview.documentId} title={preview.title} focusChunkId={preview.chunkId} focusPage={preview.page} onClose={() => setPreview(null)} />}
    </div>
  );
}
