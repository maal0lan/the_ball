"""Providers: the built-in Ollama plus any number of custom OpenAI-compatible endpoints.

Custom providers live in the setting `llm.providers` (a JSON list) and the active one is `llm.provider`.
Each entry: {id, name, baseUrl, apiKey, enabled, models: {fast, mid, heavy}}.
"""
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from config import settings
from llm import LLMError, ollama

log = logging.getLogger("backend.providers")


@dataclass
class Provider:
    id: str
    name: str
    kind: str                 # "ollama" | "openai"
    base_url: str = ""
    api_key: str = ""
    models: dict | None = None

    def model(self, tier: str) -> str:
        if self.kind == "ollama":
            return str(settings.get(f"llm.model.{tier}"))
        return str((self.models or {}).get(tier) or (self.models or {}).get("mid") or "")


def custom_providers() -> list[Provider]:
    try:
        raw = json.loads(str(settings.get("llm.providers")) or "[]")
    except Exception:
        log.warning("llm.providers is not valid JSON; ignoring it")
        return []
    out = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict) and p.get("enabled", True) and p.get("id") and p.get("baseUrl"):
            out.append(Provider(str(p["id"]), str(p.get("name") or p["id"]), "openai",
                                str(p["baseUrl"]).rstrip("/"), str(p.get("apiKey") or ""), p.get("models") or {}))
    return out


def all_providers() -> list[Provider]:
    return [Provider("ollama", "Ollama", "ollama"), *custom_providers()]


def active() -> Provider:
    want = str(settings.get("llm.provider") or "ollama")
    for p in all_providers():
        if p.id == want:
            return p
    log.warning("Provider '%s' is missing or disabled; falling back to Ollama", want)
    return all_providers()[0]


async def chat_stream(p: Provider, model: str, messages: list[dict], max_tokens: int | None = None) -> AsyncIterator[str]:
    if p.kind == "ollama":
        async for t in ollama.chat_stream(model, messages, max_tokens):
            yield t
        return
    if not model:
        raise LLMError(f"Provider '{p.name}' has no model set for this effort. Fill it in Settings → Providers.")
    headers = {"Content-Type": "application/json"}
    if p.api_key:
        headers["Authorization"] = f"Bearer {p.api_key}"
    payload = {"model": model, "messages": messages, "stream": True,
               "temperature": float(settings.get("llm.temperature")), "top_p": float(settings.get("llm.topP")),
               "max_tokens": int(max_tokens or settings.get("llm.maxTokens"))}
    if settings.get("debug.logPrompts"):
        log.debug("PROMPT -> %s @ %s\n%s", model, p.name, json.dumps(messages, ensure_ascii=False, indent=1))
    timeout = httpx.Timeout(float(settings.get("llm.timeout")), connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", f"{p.base_url}/chat/completions", json=payload, headers=headers) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", "replace")[:300]
                    hint = {401: "API key rejected", 403: "API key not allowed for this model", 404: "model or URL not found",
                            429: "rate limited or out of credit"}.get(r.status_code, "request failed")
                    raise LLMError(f"{p.name}: HTTP {r.status_code} ({hint}). {body}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        ch = json.loads(data).get("choices") or []
                    except json.JSONDecodeError:
                        continue
                    piece = (ch[0].get("delta") or {}).get("content") if ch else None
                    if piece:
                        yield piece
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise LLMError(f"Cannot reach {p.name} at {p.base_url}. Check the API link.")
    except httpx.ReadTimeout:
        raise LLMError(f"{p.name} timed out after {settings.get('llm.timeout')}s.")


async def test(p: Provider, tier: str) -> dict:
    model = p.model(tier)
    out = ""
    try:
        async for t in chat_stream(p, model, [{"role": "user", "content": "Say hello in five words."}], 24):
            out += t
        return {"ok": True, "provider": p.name, "model": model, "reply": out.strip()}
    except LLMError as e:
        return {"ok": False, "provider": p.name, "model": model, "error": str(e)}