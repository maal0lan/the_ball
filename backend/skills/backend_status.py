"""
Backend process: status of Ollama, the model tiers, TTS, the workspace folder and the
history DB; plus a restart switch.

`backend_status` is read-only. `backend_restart` exits the Python process so the Electron
supervisor (backend.js) restarts it — same as a crash restart. It refuses unless you pass
confirm='yes'.
"""
import asyncio
import logging
import os
import time

import history
import tools
from config import settings
from llm import ollama
from tools import ToolError
from tts import phonon

log = logging.getLogger("backend.skills.backend_status")
STARTED = time.time()


def backend_status() -> str:
    root = tools.workspace_root()
    try:
        models = asyncio.run(ollama.list_models())
        reachable = True
    except Exception as e:  # Ollama down or misconfigured — report, don't crash
        models = []
        reachable = False
        log.warning("backend_status: ollama unreachable: %s", e)
    tiers = {t: settings.get(f"llm.model.{t}") for t in ("fast", "mid", "heavy")}
    db = history._DB or "(not opened yet)"
    lines = [
        f"Uptime: {time.time() - STARTED:.0f}s",
        f"Ollama: {ollama.host} — reachable, {len(models)} model(s)" if reachable
        else f"Ollama: {ollama.host} — NOT reachable (is `ollama serve` running?)",
        f"Tiers: fast={tiers['fast']}, mid={tiers['mid']}, heavy={tiers['heavy']}",
        f"TTS: engine={settings.get('voice.engine')} model={settings.get('voice.model')} "
        f"loaded={bool(phonon.loaded)}",
        f"Workspace: {root if root else '(none set — chat only)'}",
        f"History DB: {db}",
        f"Installed models: {', '.join(models) if models else '(none)'}",
    ]
    return "\n".join(lines)


def backend_restart(confirm: str = "no") -> str:
    if str(confirm).strip().lower() != "yes":
        raise ToolError("Refusing to restart the backend — pass confirm='yes' to proceed.")
    log.warning("backend_restart requested by skill — exiting; the Electron supervisor should restart the process")
    os._exit(0)  # supervisor (backend.js) auto-restarts on unexpected exit


def register(register_tool):
    register_tool(name="backend_status",
                  signature="backend_status()   # backend process status: Ollama, tiers, TTS, workspace",
                  perm="misc", fn=backend_status,
                  describe=lambda a: "Checking backend status")
    register_tool(name="backend_restart",
                  signature="backend_restart(confirm='no')   # exit so the supervisor restarts the backend",
                  perm="misc", fn=backend_restart,
                  describe=lambda a: "RESTARTING the backend process")
