from __future__ import annotations

NO_ANSWER = "I could not find sufficient evidence in the provided documents to answer this question."

SYSTEM_PROMPT = f"""You are an enterprise document assistant. Answer the user's question using ONLY the numbered context passages provided.

Rules:
1. Every factual statement must be supported by the passages. Cite the supporting passage numbers in square brackets right after the statement, e.g. "Employees receive 20 days of leave [2]."
2. Do not use outside knowledge and do not guess. If the passages do not contain the answer, reply exactly: "{NO_ANSWER}"
3. If the passages only partially answer the question, answer the supported part, then say which part is not covered by the documents.
4. When exact wording matters (figures, limits, definitions, obligations), quote the passage in double quotes.
5. Be concise and precise: answer in 1-4 sentences. Prefer specific values (numbers, dates, names) from the passages.
6. Do not list or repeat the passages; only put their numbers in brackets inside your sentences.

Example of the expected format:
Question: How many days of leave do employees get?
Answer: Employees receive "20 days of paid vacation per calendar year" [1], increasing to 25 days after 5 years of service [2]."""


def format_passage(i: int, chunk: dict) -> str:
    pages = chunk.get("page_start")
    if pages and chunk.get("page_end") and chunk["page_end"] != pages:
        pages = f"{pages}-{chunk['page_end']}"
    meta = [chunk.get("title") or chunk.get("filename") or "document"]
    if chunk.get("doc_date"):
        meta.append(f"dated {chunk['doc_date']}")
    if pages:
        meta.append(f"p. {pages}")
    section = (chunk.get("section") or "").split(" > ")[-1]
    if section and section != meta[0]:
        meta.append(f"section \"{section}\"")
    return f"[{i}] {', '.join(meta)}:\n{chunk['text']}"


def build_messages(question: str, chunks: list[dict], history: list[dict] | None = None) -> list[dict]:
    context = "\n\n".join(format_passage(i, c) for i, c in enumerate(chunks, start=1))
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in (history or [])[-4:]:
        msgs.append({"role": m["role"], "content": m["content"][:1500]})
    msgs.append({"role": "user", "content": f"Context passages:\n\n{context}\n\nQuestion: {question}\n\nAnswer (with [n] citations):"})
    return msgs


REWRITE_PROMPT = """Rewrite the user's last message into a single standalone search question that can be understood without the conversation. Resolve pronouns and references using the conversation. Output only the rewritten question, nothing else.

Conversation:
{history}

Last message: {question}

Standalone question:"""
