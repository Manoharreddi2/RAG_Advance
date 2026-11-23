// Typed API client for the FastAPI backend.
const BASE = (import.meta.env.VITE_API_URL ?? "") + "/api/v1";

export type Role = "viewer" | "editor" | "admin";
export interface User { id: string; email: string; full_name: string | null; role: Role; is_active: boolean; created_at: string }
export interface Doc {
  id: string; filename: string; title: string | null; mime_type: string; size_bytes: number; category: string | null;
  author: string | null; doc_date: string | null; tags: string[]; version: number; status: string; error: string | null;
  page_count: number | null; chunk_count: number; created_at: string; updated_at: string;
}
export interface Chunk { id: string; chunk_index: number; text: string; section_path: string | null; page_start: number | null; page_end: number | null; chunk_type: string; token_count: number }
export interface Source {
  chunk_id: string; document_id: string; filename: string; title: string | null; section: string | null;
  page_start: number | null; page_end: number | null; chunk_type: string; category: string | null; author: string | null;
  doc_date: string | null; text: string; score: number; scores: Record<string, number>; ranks: Record<string, number>;
}
export interface Citation { index: number; chunk_id: string; document_id: string; filename: string; title: string | null; page_start: number | null; page_end: number | null; section: string | null; quote: string }
export interface RetrievalConfig { mode: "dense" | "bm25" | "hybrid"; top_k: number; candidates: number; rrf_k: number; rerank: boolean; rerank_depth: number; use_filters: boolean }
export interface Filters { document_ids?: string[]; filenames?: string[]; categories?: string[]; authors?: string[]; date_from?: string | null; date_to?: string | null }
export interface Facets { categories: string[]; authors: string[]; filenames: string[]; date_min: string | null; date_max: string | null }

export const DEFAULT_CONFIG: RetrievalConfig = { mode: "hybrid", top_k: 5, candidates: 30, rrf_k: 60, rerank: true, rerank_depth: 30, use_filters: true };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

let token: string | null = localStorageGet("edi_token");
export function setToken(t: string | null) {
  token = t;
  try { t ? localStorage.setItem("edi_token", t) : localStorage.removeItem("edi_token"); } catch { /* storage unavailable */ }
}
export function getToken() { return token; }
function localStorageGet(k: string) { try { return localStorage.getItem(k); } catch { return null; } }

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof URLSearchParams)) headers.set("Content-Type", "application/json");
  const res = await fetch(BASE + path, { ...init, headers });
  if (res.status === 401) onUnauthorized();
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* not json */ }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password }) }),
  register: (email: string, password: string, full_name?: string) =>
    request<{ access_token: string; user: User }>("/auth/register", { method: "POST", body: JSON.stringify({ email, password, full_name }) }),
  me: () => request<User>("/auth/me"),
  users: () => request<User[]>("/users"),
  updateUser: (id: string, body: Partial<Pick<User, "role" | "is_active">>) => request<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  documents: (params: Record<string, string> = {}) => request<{ items: Doc[]; total: number }>(`/documents?${new URLSearchParams(params)}`),
  facets: () => request<Facets>("/documents/facets"),
  upload: (form: FormData) => request<{ filename: string; status: string; detail: string | null; document: Doc | null }[]>("/documents", { method: "POST", body: form }),
  chunks: (id: string) => request<Chunk[]>(`/documents/${id}/chunks`),
  reindex: (id: string) => request<Doc>(`/documents/${id}/reindex`, { method: "POST" }),
  updateDoc: (id: string, body: Partial<Doc>) => request<Doc>(`/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteDoc: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  fileBlob: async (id: string) => {
    const res = await fetch(`${BASE}/documents/${id}/file`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "Could not load file");
    return res.blob();
  },

  search: (query: string, config: RetrievalConfig, filters: Filters) =>
    request<{ results: Source[]; timings_ms: Record<string, number> }>("/search", { method: "POST", body: JSON.stringify({ query, config, filters }) }),
  conversations: () => request<{ id: string; title: string; updated_at: string }[]>("/conversations"),
  conversation: (id: string) => request<{ id: string; title: string; messages: { id: string; role: string; content: string; citations: Citation[]; created_at: string }[] }>(`/conversations/${id}`),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),

  analytics: (days: number) => request<any>(`/analytics/summary?days=${days}`),
  queries: (limit = 50) => request<any[]>(`/analytics/queries?limit=${limit}`),
  evalRuns: () => request<any[]>("/eval/runs"),
  evalRun: (id: string) => request<any>(`/eval/runs/${id}`),
  importEval: () => request<{ imported: number }>("/eval/import", { method: "POST" }),
};

export type ChatEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "rewrite"; standalone_query: string }
  | { type: "sources"; chunks: Source[]; timings_ms: Record<string, number>; cached?: boolean }
  | { type: "token"; text: string }
  | { type: "done"; answer: string; citations: Citation[]; quotes: { quote: string; verified: boolean }[]; abstained: boolean; usage: Record<string, number>; timings_ms: Record<string, number>; model: string; cache_hit: boolean; standalone_query: string; conversation_id: string }
  | { type: "error"; detail: string };

/** POST + Server-Sent Events reader (EventSource cannot POST or send auth headers). */
export async function streamChat(body: object, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST", signal,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (res.status === 401) onUnauthorized();
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail; } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = raw.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  }
}
