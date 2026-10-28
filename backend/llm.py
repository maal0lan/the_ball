"""Async Ollama client (streaming /api/chat) with human-readable errors."""
import json
import logging
from typing import AsyncIterator

import httpx

from config import settings

log = logging.getLogger("backend.llm")


class LLMError(Exception):
    """Raised with a message that is safe and useful to show the user."""


class OllamaClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def host(self) -> str:
        return str(settings.get("llm.host")).rstrip("/")

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(float(settings.get("llm.timeout")), connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def list_models(self) -> list[str]:
        try:
            r = await self._c().get(f"{self.host}/api/tags", timeout=5.0)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except Exception as e:
            log.warning("Cannot list Ollama models at %s: %s", self.host, e)
            return []

    async def warmup(self, model: str) -> None:
        try:
            await self._c().post(f"{self.host}/api/generate", json={
                "model": model, "prompt": "", "keep_alive": settings.get("llm.keepAlive")}, timeout=300.0)
            log.info("Warmed up model %s", model)
        except Exception as e:
            log.warning("Warm-up of %s failed: %s", model, e)

    def _options(self, max_tokens: int | None = None) -> dict:
        o = {
            "temperature": float(settings.get("llm.temperature")),
            "top_p": float(settings.get("llm.topP")),
            "top_k": int(settings.get("llm.topK")),
            "repeat_penalty": float(settings.get("llm.repeatPenalty")),
            "num_predict": int(max_tokens or settings.get("llm.maxTokens")),
            "num_ctx": int(settings.get("llm.numCtx")),
        }
        seed = int(settings.get("llm.seed"))
        if seed >= 0:
            o["seed"] = seed
        stop = settings.csv("llm.stop")
        if stop:
            o["stop"] = stop
        return o

    async def chat_stream(self, model: str, messages: list[dict], max_tokens: int | None = None) -> AsyncIterator[str]:
        payload = {"model": model, "messages": messages, "stream": True,
                   "keep_alive": settings.get("llm.keepAlive"), "options": self._options(max_tokens)}
        if settings.get("debug.logPrompts"):
            log.debug("PROMPT -> %s\n%s", model, json.dumps(messages, ensure_ascii=False, indent=1))
        try:
            async with self._c().stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                if resp.status_code == 404:
                    raise LLMError(f"Model '{model}' is not installed. Run:  ollama pull {model}")
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise LLMError(f"Ollama returned HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMError(f"Ollama error: {data['error']}")
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise LLMError(f"Cannot reach Ollama at {self.host}. Start it with:  ollama serve")
        except httpx.ReadTimeout:
            raise LLMError(f"Model '{model}' timed out after {settings.get('llm.timeout')}s "
                           "(first load of a big model can be slow — raise the timeout in Settings → Brain).")


ollama = OllamaClient()


def pick_tier(text: str, tools_active: bool) -> str:
    """Return fast, mid, or heavy according to llm.mode and the auto rules."""
    mode = str(settings.get("llm.mode"))
    if mode in ("fast", "mid", "heavy"):
        return mode
    words = len(text.split())
    lower = text.lower()
    if tools_active and any(k in lower for k in settings.csv("llm.autoHeavyKeywords")):
        return "heavy"
    if words >= int(settings.get("llm.autoHeavyWords")):
        return "heavy"
    if words >= int(settings.get("llm.autoMidWords")):
        return "mid"
    return "fast"


def pick_model(text: str, tools_active: bool) -> tuple[str, str]:
    """Ollama-only compatibility helper."""
    tier = pick_tier(text, tools_active)
    return tier, str(settings.get(f"llm.model.{tier}"))
