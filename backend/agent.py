"""
One conversation turn: build prompt -> stream LLM -> run tools -> speak sentences.

Everything the UI needs is sent through the `emit` coroutine as small JSON events.
"""
import asyncio
import base64
import json
import logging
import re
import time
import uuid
from typing import Awaitable, Callable

import history
import tools
from config import settings
from llm import LLMError, ollama, pick_model
from tts import SentenceSplitter, clean_for_speech, phonon

log = logging.getLogger("backend.agent")
Emit = Callable[[dict], Awaitable[None]]

OPEN, CLOSE = "<tool>", "</tool>"


class ToolStreamFilter:
    """Hides <tool>{json}</tool> from the visible/spoken text and captures the JSON."""

    def __init__(self) -> None:
        self.buf = ""
        self.in_tool = False
        self.done = False
        self.tool_text = ""

    def feed(self, s: str) -> str:
        if self.done:
            return ""
        self.buf += s
        out = ""
        while True:
            if not self.in_tool:
                i = self.buf.find(OPEN)
                if i >= 0:
                    out += self.buf[:i]
                    self.buf = self.buf[i + len(OPEN):]
                    self.in_tool = True
                    continue
                keep = 0
                for k in range(min(len(OPEN) - 1, len(self.buf)), 0, -1):
                    if OPEN.startswith(self.buf[-k:]):
                        keep = k
                        break
                out += self.buf[:len(self.buf) - keep]
                self.buf = self.buf[len(self.buf) - keep:]
                return out
            j = self.buf.find(CLOSE)
            if j >= 0:
                self.tool_text, self.buf, self.done = self.buf[:j], "", True
            return out

    def flush(self) -> str:
        if self.in_tool and not self.done:  # model forgot </tool>: still try to use it
            self.tool_text, self.done = self.buf, True
            self.buf = ""
            return ""
        out, self.buf = self.buf, ""
        return out


def parse_tool_call(raw: str) -> tuple[str, dict]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object found inside <tool>")
    data = json.loads(m.group(0))
    name = data.get("name")
    args = data.get("args", data.get("arguments", {})) or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        raise ValueError('expected {"name": str, "args": object}')
    return name, args


def build_system_prompt() -> str:
    name = str(settings.get("llm.assistantName"))
    base = str(settings.get("llm.systemPrompt")).replace("{name}", name)
    avail = tools.enabled_tools()
    if not avail:
        return base
    root = tools.workspace_root()
    lines = "\n".join(f"  {tools.signature(t)}" for t in avail)
    extra = str(settings.get("agent.extraInstructions") or "").strip()
    return (
        f"{base}\n\nYou can work with files in the user's workspace folder ({root.name}). "
        "To use a tool, write exactly one block like this and then stop:\n"
        f'{OPEN}{{"name": "read_file", "args": {{"path": "notes/todo.md"}}}}{CLOSE}\n'
        f"Available tools:\n{lines}\n"
        "Paths are relative to the workspace. After you receive the tool result, answer in plain spoken "
        "language. Never invent file contents; if a tool fails, say what went wrong."
        + (f"\n{extra}" if extra else "")
    )


class SpeechQueue:
    """Turns sentences into audio events, in order, while the LLM keeps writing."""

    def __init__(self, emit: Emit) -> None:
        self.emit = emit
        self.q: asyncio.Queue = asyncio.Queue()
        self.seq = 0
        self.split = SentenceSplitter()
        self.task = asyncio.create_task(self._worker())
        self.enabled = bool(settings.get("voice.enabled")) and settings.get("voice.engine") != "off"
        self.engine = str(settings.get("voice.engine"))
        self.sentence_streaming = bool(settings.get("voice.sentenceStreaming"))
        self.held: list[str] = []

    def feed(self, text: str) -> None:
        if not self.enabled:
            return
        sents = self.split.feed(text)
        if self.sentence_streaming:
            for s in sents:
                self.q.put_nowait(s)
        else:
            self.held += sents

    async def finish(self) -> None:
        if self.enabled:
            for s in self.split.flush():
                self.held.append(s) if not self.sentence_streaming else self.q.put_nowait(s)
            for s in self.held:
                self.q.put_nowait(s)
        self.q.put_nowait(None)
        await self.task

    def cancel(self) -> None:
        self.task.cancel()

    async def _worker(self) -> None:
        while True:
            s = await self.q.get()
            if s is None:
                break
            text = clean_for_speech(s)
            if not re.search(r"\w", text):
                continue
            self.seq += 1
            try:
                if self.engine == "system":
                    await self.emit({"type": "speak", "seq": self.seq, "text": text})
                else:
                    t0 = time.time()
                    wav = await phonon.synthesize(text)
                    log.debug("TTS %.1fs for %d chars", time.time() - t0, len(text))
                    await self.emit({"type": "audio", "seq": self.seq, "text": text,
                                     "wav": base64.b64encode(wav).decode("ascii")})
            except Exception as e:
                log.exception("TTS failed")
                await self.emit({"type": "error", "where": "tts", "message": f"Voice failed: {e}"})
                break  # don't spam an error per sentence
        await self.emit({"type": "speech_done"})


async def run_turn(session_id: str, text: str, emit: Emit,
                   confirm: Callable[[str, str], Awaitable[bool]]) -> None:
    t_start = time.time()
    tool_list = tools.enabled_tools()
    tier, model = pick_model(text, bool(tool_list))
    log.info("Turn: tier=%s model=%s tools=%s", tier, model, tool_list or "none")
    await emit({"type": "turn_start", "tier": tier, "model": model})

    if settings.get("history.enabled"):
        history.save_message(session_id, "user", text)

    n_turns = int(settings.get("llm.historyTurns"))
    past = history.get_session_messages(session_id)[:-1] if settings.get("history.enabled") else []
    past = [{"role": m["role"], "content": m["content"]} for m in past][-(n_turns * 2):] if n_turns else []
    messages = [{"role": "system", "content": build_system_prompt()}, *past, {"role": "user", "content": text}]

    speech = SpeechQueue(emit)
    visible_all = ""
    try:
        for step in range(int(settings.get("agent.maxSteps")) + 1):
            filt = ToolStreamFilter()
            raw = ""
            async for tok in ollama.chat_stream(model, messages):
                raw += tok
                vis = filt.feed(tok)
                if vis:
                    visible_all += vis
                    speech.feed(vis)
                    await emit({"type": "token", "text": vis})
                if filt.done:
                    break
            tail = filt.flush()
            if tail:
                visible_all += tail
                speech.feed(tail)
                await emit({"type": "token", "text": tail})
            if settings.get("debug.logPrompts"):
                log.debug("REPLY <- %s (step %d)\n%s", model, step, raw)

            if not filt.done:
                break
            if step >= int(settings.get("agent.maxSteps")):
                await emit({"type": "info", "message": "Stopped: reached the max tool steps."})
                break

            try:
                name, args = parse_tool_call(filt.tool_text)
            except Exception as e:
                log.warning("Bad tool call %r: %s", filt.tool_text[:200], e)
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"Tool call was invalid ({e}). Use the exact format shown."}]
                continue

            desc = tools.describe(name, args)
            await emit({"type": "tool_call", "name": name, "args": args, "description": desc})
            if tools.needs_confirmation(name) and name in tools.enabled_tools():
                if not await confirm(name, desc):
                    result = {"ok": False, "error": "The user denied this action."}
                else:
                    result = await asyncio.to_thread(tools.execute, name, args)
            else:
                result = await asyncio.to_thread(tools.execute, name, args)
            await emit({"type": "tool_result", "name": name, "ok": result["ok"]})
            payload = result.get("result") if result["ok"] else f"ERROR: {result['error']}"
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"<tool_result>\n{payload}\n</tool_result>\nNow answer the user."}]

        await speech.finish()
        if settings.get("history.enabled"):
            history.save_message(session_id, "assistant", visible_all, model)
        await emit({"type": "done", "text": visible_all, "model": model, "tier": tier,
                    "seconds": round(time.time() - t_start, 2)})
    except asyncio.CancelledError:
        speech.cancel()
        if visible_all.strip() and settings.get("history.enabled"):
            history.save_message(session_id, "assistant", visible_all + " …(stopped)", model)
        raise
    except LLMError as e:
        speech.cancel()
        log.error("LLM error: %s", e)
        await emit({"type": "error", "where": "llm", "message": str(e)})
        await emit({"type": "done", "text": visible_all, "model": model, "tier": tier, "seconds": 0, "failed": True})
    except Exception as e:
        speech.cancel()
        log.exception("Turn crashed")
        await emit({"type": "error", "where": "agent", "message": f"{type(e).__name__}: {e}"})
        await emit({"type": "done", "text": visible_all, "model": model, "tier": tier, "seconds": 0, "failed": True})


new_id = lambda: uuid.uuid4().hex[:10]
