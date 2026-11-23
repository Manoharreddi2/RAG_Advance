import type { ReactNode } from "react";

export const pages = (a: number | null, b: number | null) => (a ? (b && b !== a ? `pp. ${a}–${b}` : `p. ${a}`) : "");

export function bytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

const STOP = new Set("the a an and or of to in on for is are was what how when which who does do with by at from be".split(" "));

/** Highlight query terms (length >= 3, not stopwords) inside text. */
export function highlight(text: string, query: string): ReactNode {
  const terms = query.toLowerCase().match(/[a-z0-9][a-z0-9.\-]{2,}/g)?.filter((t) => !STOP.has(t)) ?? [];
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
export const fix = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "–" : v.toFixed(d));
export const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
