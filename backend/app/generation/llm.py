"""LLM providers with a single streaming interface.

``stream(messages)`` yields ``("token", str)`` events and finishes with one ``("usage", dict)`` event
containing prompt/completion token counts and the model name. Providers:

* ``openai``            — OpenAI Chat Completions (needs OPENAI_API_KEY)
* ``openai_compatible`` — any OpenAI-compatible server (Ollama, vLLM, LM Studio, TGI) via OPENAI_BASE_URL
* ``local``             — Hugging Face transformers model running in-process (CPU or GPU)
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from functools import lru_cache

from app.config import get_settings
from app.logging import get_logger

log = get_logger("llm")


class LLMError(RuntimeError):
    pass


class BaseLLM:
    name: str = "base"

    async def stream(self, messages: list[dict], max_tokens: int | None = None,
                     temperature: float | None = None) -> AsyncIterator[tuple[str, object]]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def complete(self, messages: list[dict], max_tokens: int | None = None,
                       temperature: float | None = None) -> tuple[str, dict]:
        parts, usage = [], {}
        async for kind, val in self.stream(messages, max_tokens, temperature):
            if kind == "token":
                parts.append(val)
            else:
                usage = val
        return "".join(parts), usage


class OpenAILLM(BaseLLM):
    def __init__(self, model: str, api_key: str | None, base_url: str | None = None):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=120, max_retries=2)
        self.name = model
        self.compatible = base_url is not None

    async def stream(self, messages, max_tokens=None, temperature=None):
        s = get_settings()
        kwargs = dict(model=self.name, messages=messages, stream=True,
                      max_tokens=max_tokens or s.llm_max_tokens,
                      temperature=s.llm_temperature if temperature is None else temperature)
        if not self.compatible:
            kwargs["stream_options"] = {"include_usage": True}
        try:
            resp = await self.client.chat.completions.create(**kwargs)
            usage, n_chars = None, 0
            async for ev in resp:
                if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
                    n_chars += len(ev.choices[0].delta.content)
                    yield "token", ev.choices[0].delta.content
                if getattr(ev, "usage", None):
                    usage = ev.usage
        except Exception as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if usage:
            yield "usage", {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                            "model": self.name, "estimated": False}
        else:  # some compatible servers do not report usage when streaming
            prompt_chars = sum(len(m["content"]) for m in messages)
            yield "usage", {"prompt_tokens": prompt_chars // 4, "completion_tokens": n_chars // 4,
                            "model": self.name, "estimated": True}


class LocalLLM(BaseLLM):
    """In-process transformers model. Generation is serialized with a lock (one model instance)."""

    def __init__(self, model_name: str, device: str = "cpu"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        dtype = torch.float32 if device == "cpu" else torch.float16
        self.model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype).to(device).eval()
        self.device = device
        self.name = model_name
        self._lock = threading.Lock()

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))

    async def stream(self, messages, max_tokens=None, temperature=None):
        from transformers import TextIteratorStreamer
        s = get_settings()
        temperature = s.llm_temperature if temperature is None else temperature
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        n_prompt = int(inputs["input_ids"].shape[1])
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=600)
        gen_kwargs = dict(**inputs, streamer=streamer, max_new_tokens=max_tokens or s.llm_max_tokens,
                          do_sample=temperature > 0, repetition_penalty=1.05,
                          pad_token_id=self.tokenizer.eos_token_id)
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
        out_holder: dict = {}

        def run():
            with self._lock, self.torch.inference_mode():
                try:
                    out_holder["ids"] = self.model.generate(**gen_kwargs)
                except Exception as e:  # surface errors to the consumer
                    out_holder["error"] = e
                    streamer.end()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        loop = asyncio.get_running_loop()
        it = iter(streamer)
        sentinel = object()
        while True:
            tok = await loop.run_in_executor(None, next, it, sentinel)
            if tok is sentinel:
                break
            if tok:
                yield "token", tok
        await loop.run_in_executor(None, thread.join)
        if "error" in out_holder:
            raise LLMError(str(out_holder["error"]))
        n_completion = int(out_holder["ids"].shape[1]) - n_prompt
        yield "usage", {"prompt_tokens": n_prompt, "completion_tokens": n_completion, "model": self.name,
                        "estimated": False}


@lru_cache
def get_llm() -> BaseLLM:
    s = get_settings()
    provider = s.resolved_llm_provider
    log.info("llm_provider", provider=provider)
    if provider == "openai":
        if not s.openai_api_key:
            raise LLMError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAILLM(s.openai_model, s.openai_api_key)
    if provider == "openai_compatible":
        return OpenAILLM(s.openai_model, s.openai_api_key, s.openai_base_url)
    return LocalLLM(s.local_llm_model, s.device)


def cost_usd(usage: dict) -> float:
    """Cost from token usage and configured per-1M-token prices (0 for local models unless configured)."""
    s = get_settings()
    if s.resolved_llm_provider == "local":
        return 0.0
    return (usage.get("prompt_tokens", 0) * s.price_input_per_m + usage.get("completion_tokens", 0) * s.price_output_per_m) / 1e6
