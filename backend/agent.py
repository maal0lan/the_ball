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
from llm import LLMError, pick_tier
import providers
from tts import SentenceSplitter, clean_for_speech, phonon

log = logging.getLogger("backend.agent")
Emit = Callable[[dict], Awaitable[None]]

OPEN, CLOSE = "<tool>", "</tool>"

# Real models rarely follow the requested format exactly. Mistral 7B, for example, writes things like
#   [tool] [name]: {"name": "write_file", ...}          or   ```json {"name": ...} ```
#   or its native   [TOOL_CALLS] [{"name": ..., "arguments": {...}}]
# so we accept ANY of these openers, then look for the first complete JSON object that looks like a call.
_OPEN_RE = re.compile(r'<tool|\[tool|```|\{\s*"(?:name|function|tool)"', re.I)
_OPEN_LITERALS = ['<tool', '[tool', '```', '{"name"', '{ "name"', '{"function"', '{"tool"']


def _partial_open_len(buf: str) -> int:
    """How many trailing characters of buf might be the start of an opener (so we hold them back)."""
    low = buf.lower()
    for k in range(min(max(map(len, _OPEN_LITERALS)) - 1, len(low)), 0, -1):
        if any(lit.startswith(low[-k:]) for lit in _OPEN_LITERALS):
            return k
    return 0


def find_json_object(text: str) -> str | None:
    """First balanced {...} in text (string/escape aware), or None if it is incomplete or absent."""
    i = text.find("{")
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def extract_tool_call(text: str) -> tuple[str, dict] | None:
    """Return (name, args) if text contains a complete, recognisable tool call, else None."""
    obj = find_json_object(text)
    if obj is None:
        return None
    try:
        data = json.loads(obj, strict=False)        # strict=False: models put raw newlines inside strings
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("function"), dict):
        data = data["function"]
    if not isinstance(data, dict):
        return None
    name = data.get("name") or data.get("tool")
    args = data.get("args", data.get("arguments", data.get("parameters")))
    if not isinstance(name, str):
        return None
    if args is None:
        if name not in tools.REGISTRY:               # a bare {"name": "x"} that is not a tool (e.g. package.json)
            return None
        args = {}
    if isinstance(args, str):
        try:
            args = json.loads(args, strict=False)
        except ValueError:
            return None
    return (name, args) if isinstance(args, dict) else None


def looks_like_tool(text: str) -> bool:
    low = text.lower()
    return ("<tool" in low or "[tool" in low or
            (re.search(r'"name"\s*:', text) is not None and re.search(r'"(args|arguments|parameters)"\s*:', text) is not None))


class ToolStreamFilter:
    """
    Streams ordinary text through untouched, but the moment something that might be a tool call starts
    (<tool, [tool, ``` or {"name") it HOLDS everything back. Once a complete call is recognised the stream
    can be cut (done=True). At the end, held text that was not a tool call (a normal code block) is released.
    """

    def __init__(self) -> None:
        self.pending = ""
        self.held = ""
        self.holding = False
        self.done = False
        self.suspect = False      # looked like a tool call but was malformed / cut off
        self.tool_text = ""

    def feed(self, s: str) -> str:
        if self.done:
            return ""
        if self.holding:
            self.held += s
            self._check()
            return ""
        self.pending += s
        m = _OPEN_RE.search(self.pending)
        if m:
            out, self.held, self.pending, self.holding = self.pending[:m.start()], self.pending[m.start():], "", True
            self._check()
            return out
        k = _partial_open_len(self.pending)
        out, self.pending = self.pending[:len(self.pending) - k], self.pending[len(self.pending) - k:]
        return out

    def _check(self) -> None:
        if extract_tool_call(self.held) is not None:
            self.done, self.tool_text = True, self.held

    def flush(self) -> str:
        """Text that should still be shown when the stream ends."""
        if self.done:
            return ""
        if not self.holding:
            out, self.pending = self.pending, ""
            return out
        if looks_like_tool(self.held):
            self.suspect = True
            return ""
        out, self.held = self.held, ""
        return out


def parse_tool_call(raw: str) -> tuple[str, dict]:
    call = extract_tool_call(raw)
    if call is None:
        raise ValueError("no complete tool call found (invalid JSON, or the reply was cut off)")
    return call


def _example_call(avail: list[str]) -> str:
    """A format example that uses a tool the model is actually allowed to call."""
    samples = {
        "write_file": ("write_file", {"path": "notes/todo.md", "content": "first line\nsecond line"}),
        "read_file": ("read_file", {"path": "notes/todo.md"}),
        "list_dir": ("list_dir", {"path": "."}),
        "run_command": ("run_command", {"command": "git status"}),
    }
    for key in samples:
        if key in avail:
            name, args = samples[key]
            break
    else:
        name, args = avail[0], {}
    return f'{OPEN}{json.dumps({"name": name, "args": args})}{CLOSE}'


def build_system_prompt() -> str:
    name = str(settings.get("llm.assistantName"))
    base = str(settings.get("llm.systemPrompt")).replace("{name}", name)
    avail = tools.enabled_tools()
    if not avail:
        return base
    root = tools.workspace_root()
    lines = "\n".join(f"  {tools.signature(t)}" for t in avail)
    extra = str(settings.get("agent.extraInstructions") or "").strip()
    inst = tools.instruction_skills() if "use_skill" in avail else []
    skills_block = ("Instruction skills (call use_skill(name) to read one BEFORE doing a task it covers):\n"
                    + "\n".join(f"  - {s['name']}: {s['description']}" for s in inst) + "\n") if inst else ""
    where = f"The user's workspace folder is '{root.name}'; paths are relative to it. " if root else ""
    return (
        f"{base}\n\nYou can act on the user's computer with tools. {where}"
        "To use a tool, reply with ONLY one tool block and nothing else: no explanation before it, no code fence, no markdown. Exactly:\n"
        f"{_example_call(avail)}\n"
        "Inside the JSON, write new lines as \\n and escape double quotes. One tool per reply.\n"
        f"Available tools:\n{lines}\n"
        f"{skills_block}"
        "When the user asks you to create, save, read, list, search or run something, you MUST use the matching tool. "
        "Never paste file contents into the chat instead of saving them with a tool, and never claim you did something until a "
        "tool result confirms it. After the tool result arrives, tell the user what happened in one or two plain sentences."
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
    tier = pick_tier(text, bool(tool_list))
    prov = providers.active()
    model = prov.model(tier)
    log.info("Turn: provider=%s tier=%s model=%s tools=%s", prov.name, tier, model, tool_list or "none")
    await emit({"type": "turn_start", "tier": tier, "model": model, "provider": prov.name})

    if settings.get("history.enabled"):
        history.save_message(session_id, "user", text)

    n_turns = int(settings.get("llm.historyTurns"))
    past = history.get_session_messages(session_id)[:-1] if settings.get("history.enabled") else []
    past = [{"role": m["role"], "content": m["content"]} for m in past][-(n_turns * 2):] if n_turns else []
    messages = [{"role": "system", "content": build_system_prompt()}, *past, {"role": "user", "content": text}]

    # Writing a file means emitting its whole content inside the tool call, so allow more tokens than a chat reply.
    tool_budget = max(int(settings.get("llm.maxTokens")), int(settings.get("agent.toolMaxTokens"))) if tool_list else None
    speech = SpeechQueue(emit)
    visible_all = ""
    try:
        for step in range(int(settings.get("agent.maxSteps")) + 1):
            filt = ToolStreamFilter()
            raw = ""
            async for tok in providers.chat_stream(prov, model, messages, tool_budget):
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

            if filt.suspect:
                log.warning("Malformed or cut-off tool call from %s: %r", model, filt.held[:300])
                await emit({"type": "info", "message": "The model started a tool call but it was malformed or cut off. "
                            "Retrying… (if this repeats: raise Settings → Agent → Max tokens for tool calls, or use a bigger model)"})
                if step >= int(settings.get("agent.maxSteps")):
                    break
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": 'Your tool call was invalid or incomplete. Reply with ONLY: <tool>{"name": "...", "args": {...}}</tool> '
                                                         "with valid JSON (new lines as \\n, escaped quotes) and keep file contents short."}]
                continue
            if not filt.done:
                break
            if step >= int(settings.get("agent.maxSteps")):
                await emit({"type": "info", "message": "Stopped: reached the max tool steps."})
                break

            try:
                name, args = parse_tool_call(filt.tool_text)
                log.info("Parsed tool call: %s %s", name, json.dumps(args, ensure_ascii=False)[:200])
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
