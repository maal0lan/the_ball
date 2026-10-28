"""
Debug (temporary): test each part of the pipeline in isolation and report exactly what fails.

Mirrors the backend's /api/test/* endpoints as agent skills:
- debug_test_llm(tier)   — chat with one Ollama tier (fast / mid / heavy)
- debug_test_tts(text)   — synthesize one sentence with Phonon
- debug_test_workspace() — check the workspace folder is reachable

Knowledge doc: ../knowledge/skills/debug_tmp.md
"""
import asyncio
import logging
import time

from config import settings
from llm import LLMError, ollama
from tts import phonon
from tools import ToolError

log = logging.getLogger("backend.skills.debug_tmp")


def _collect(agen) -> str:
    """Drain an async generator in a thread that has no running event loop."""
    async def _go() -> str:
        out = ""
        async for tok in agen:
            out += tok
        return out
    return asyncio.run(_go())


def debug_test_llm(tier: str = "fast") -> str:
    tier = str(tier).strip().lower()
    if tier not in ("fast", "mid", "heavy"):
        raise ToolError("tier must be fast, mid or heavy")
    model = str(settings.get(f"llm.model.{tier}"))
    t0 = time.time()
    try:
        out = _collect(ollama.chat_stream(model, [{"role": "user", "content": "Say hello in five words."}], 24))
        return f"{tier} ({model}): OK — “{out.strip()}” — {time.time() - t0:.1f}s"
    except LLMError as e:
        return f"{tier} ({model}): FAILED — {e}"
    except Exception as e:
        log.exception("debug_test_llm %s", tier)
        return f"{tier} ({model}): FAILED — {type(e).__name__}: {e}"


def debug_test_tts(text: str = "Crystal voice check. Can you hear me?") -> str:
    if str(settings.get("voice.engine")).lower() != "phonon":
        return f"TTS: skipped — voice.engine is '{settings.get('voice.engine')}', not phonon."
    t0 = time.time()
    try:
        wav = asyncio.run(phonon.synthesize(str(text)))
        return f"TTS: OK — {len(wav)} bytes in {time.time() - t0:.1f}s"
    except Exception as e:
        log.exception("debug_test_tts")
        return f"TTS: FAILED — {type(e).__name__}: {e}"


def debug_test_workspace() -> str:
    from tools import workspace_root, execute  # local import to keep this skill self-contained
    root = workspace_root()
    if not root:
        return "Workspace: FAILED — no workspace folder set (Settings → Agent → Workspace folder)."
    r = execute("list_dir", {"path": "."})
    if r["ok"]:
        preview = r["result"].replace("\n", " | ")[:140]
        return f"Workspace: OK — {root} — {preview or '(empty)'}"
    return f"Workspace: FAILED — {r.get('error')}"


def register(register_tool):
    register_tool(name="debug_test_llm",
                  signature="debug_test_llm(tier='fast')   # test one brain tier (fast/mid/heavy)",
                  perm="misc", fn=debug_test_llm,
                  describe=lambda a: f"Testing the {a.get('tier', 'fast')} model tier")
    register_tool(name="debug_test_tts",
                  signature="debug_test_tts(text='Crystal voice check. Can you hear me?')   # test TTS synthesis",
                  perm="misc", fn=debug_test_tts,
                  describe=lambda a: f"Testing TTS with {len(str(a.get('text', '')))} characters")
    register_tool(name="debug_test_workspace",
                  signature="debug_test_workspace()   # check the workspace folder is reachable",
                  perm="misc", fn=debug_test_workspace,
                  describe=lambda a: "Testing the workspace folder")
