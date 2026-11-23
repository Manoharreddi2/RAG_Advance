"""Conversational follow-ups: condense (history, follow-up) into a standalone retrieval query."""
from __future__ import annotations

from app.generation.llm import BaseLLM
from app.generation.prompts import REWRITE_PROMPT
from app.logging import get_logger

log = get_logger("rewrite")


async def standalone_question(llm: BaseLLM, question: str, history: list[dict]) -> tuple[str, dict]:
    if not history:
        return question, {}
    turns = "\n".join(f"{m['role'].capitalize()}: {m['content'][:600]}" for m in history[-4:])
    try:
        text, usage = await llm.complete([{"role": "user", "content": REWRITE_PROMPT.format(history=turns, question=question)}],
                                         max_tokens=80, temperature=0.0)
        text = text.strip().strip('"').split("\n")[0].strip()
        if 5 <= len(text) <= 400:
            return text, usage
    except Exception as e:
        log.warning("rewrite_failed", error=str(e))
    # fallback: prepend the previous user question so retrieval keeps its context
    prev = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    return f"{prev} {question}".strip(), {}
