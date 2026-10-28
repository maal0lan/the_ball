"""
Crystal backend: FastAPI on 127.0.0.1 (never exposed to the network).
Started and supervised by the Electron app, but also runnable by hand:

    python server.py --port 8765 --data-dir ./data

Auth: every HTTP call needs  Authorization: Bearer <CRYSTAL_TOKEN>  and the WebSocket needs ?token=...
(if CRYSTAL_TOKEN is unset, auth is disabled — only for manual testing).
"""
import argparse
import asyncio
import base64
import json
import logging
import re
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings, setup_logging

setup_logging(os.getenv("CRYSTAL_LOG_LEVEL", "DEBUG"))
log = logging.getLogger("backend.server")

import agent
import history
import tools
from llm import LLMError, ollama
from tts import phonon

TOKEN = os.getenv("CRYSTAL_TOKEN", "")
DATA_DIR = Path(os.getenv("CRYSTAL_DATA_DIR", "./data"))
STARTED = time.time()


def auth(request: Request) -> None:
    if TOKEN and request.headers.get("authorization") != f"Bearer {TOKEN}":
        raise HTTPException(401, "Bad or missing token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    history.init_db(DATA_DIR)
    history.prune(int(settings.get("history.retentionDays")))
    tools.load_skills()
    if settings.get("voice.engine") == "phonon" and settings.get("voice.preload"):
        threading.Thread(target=phonon.preload, daemon=True).start()
    log.info("Backend up. Python %s", sys.version.split()[0])
    yield
    await ollama.close()
    log.info("Backend stopped")


app = FastAPI(title="Crystal backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/health")
async def health():
    return {"ok": True, "uptime": round(time.time() - STARTED, 1)}


@app.get("/api/status", dependencies=[Depends(auth)])
async def status():
    models = await ollama.list_models()
    root = tools.workspace_root()
    return {
        "ollama": {"host": ollama.host, "reachable": bool(models), "models": models},
        "tiers": {t: settings.get(f"llm.model.{t}") for t in ("fast", "mid", "heavy")},
        "tts": {"engine": settings.get("voice.engine"), "model": settings.get("voice.model"), "loaded": phonon.loaded},
        "workspace": {"path": str(root) if root else None, "configured": settings.get("agent.workspace"), "tools": tools.enabled_tools(),
                      "inactive": {s["name"]: s["reason"] for s in tools.list_skills() if s.get("reason")}},
        "history_db": str(history._DB),
    }


@app.get("/api/models", dependencies=[Depends(auth)])
async def models():
    return {"llm_models": await ollama.list_models()}


@app.get("/api/settings", dependencies=[Depends(auth)])
async def get_settings():
    return settings.values


@app.post("/api/settings", dependencies=[Depends(auth)])
async def set_settings(patch: dict):
    changed = settings.update(patch)
    if changed:
        log.info("Settings changed: %s", ", ".join(changed))
    if any(k in changed for k in ("voice.model", "voice.engine", "voice.device")):
        phonon.unload()
    if any(k.startswith("llm.host") or k == "llm.timeout" for k in changed):
        await ollama.close()
        ollama._client = None
    mk = [k for k in changed if k.startswith("llm.model.")]
    if mk and settings.get("llm.warmup"):
        asyncio.create_task(ollama.warmup(str(settings.get(mk[0]))))
    return {"changed": changed}


@app.get("/api/skills", dependencies=[Depends(auth)])
async def skills():
    return {"dir": str(tools.skills_dir()), "skills": tools.list_skills()}


@app.post("/api/skills/reload", dependencies=[Depends(auth)])
async def skills_reload():
    n = tools.load_skills()
    return {"loaded_plugin_tools": n, "dir": str(tools.skills_dir()), "skills": tools.list_skills()}


@app.get("/api/history", dependencies=[Depends(auth)])
async def sessions():
    return {"sessions": history.get_sessions(), "latest": history.latest_session_id()}


@app.get("/api/history/{sid}", dependencies=[Depends(auth)])
async def session_messages(sid: str, limit: int | None = None):
    return {"session_id": sid, "messages": history.get_session_messages(sid, limit)}


@app.delete("/api/history/{sid}", dependencies=[Depends(auth)])
async def del_session(sid: str):
    history.delete_session(sid)
    return {"deleted": sid}


@app.post("/api/test/provider", dependencies=[Depends(auth)])
async def test_provider(body: dict):
    import providers
    want = str(body.get("id") or "")
    p = next((x for x in providers.all_providers() if x.id == want), None)
    if not p:
        return {"ok": False, "error": "Provider not found or disabled. Enable it and save first."}
    return await providers.test(p, str(body.get("tier") or "fast"))


@app.post("/api/test/llm", dependencies=[Depends(auth)])
async def test_llm(body: dict):
    results = {}
    for tier in body.get("tiers", ["fast", "mid", "heavy"]):
        model = str(settings.get(f"llm.model.{tier}"))
        t0 = time.time()
        try:
            out = ""
            async for tok in ollama.chat_stream(model, [{"role": "user", "content": "Say hello in five words."}], 24):
                out += tok
            results[tier] = {"model": model, "ok": True, "reply": out.strip(), "seconds": round(time.time() - t0, 2)}
        except LLMError as e:
            results[tier] = {"model": model, "ok": False, "error": str(e)}
        except Exception as e:
            log.exception("test_llm %s", tier)
            results[tier] = {"model": model, "ok": False, "error": f"{type(e).__name__}: {e}"}
    return results


@app.post("/api/test/tts", dependencies=[Depends(auth)])
async def test_tts(body: dict):
    text = body.get("text") or "Crystal voice check. Can you hear me?"
    if settings.get("voice.engine") != "phonon":
        return {"ok": True, "engine": settings.get("voice.engine"), "text": text, "wav": None}
    t0 = time.time()
    try:
        wav = await phonon.synthesize(text)
        return {"ok": True, "engine": "phonon", "seconds": round(time.time() - t0, 2),
                "wav": base64.b64encode(wav).decode("ascii")}
    except Exception as e:
        log.exception("test_tts")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/stt", dependencies=[Depends(auth)])
async def speech_to_text(request: Request):
    language = request.headers.get("x-speech-language", "en-US")[:32]
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        raise HTTPException(400, "Invalid speech language tag")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 480_000:
            raise HTTPException(413, "Voice clip cannot exceed 15 seconds.")
        chunks.append(chunk)
    pcm = b"".join(chunks)
    if not 2 <= len(pcm) <= 480_000 or len(pcm) % 2:
        raise HTTPException(400, "Voice clip must be between 1 sample and 15 seconds.")
    try:
        import stt
        text = await asyncio.to_thread(stt.transcribe_pcm16, pcm, language)
        return {"text": text}
    except Exception as exc:
        log.exception("Local speech transcription failed")
        if isinstance(exc, (OSError, ValueError)):
            detail = f"{type(exc).__name__}: {exc}"
        else:
            detail = f"{type(exc).__name__}. Check that the local Whisper model can be downloaded and loaded."
        raise HTTPException(503, f"Local speech transcription failed: {detail}") from exc


@app.post("/api/test/workspace", dependencies=[Depends(auth)])
async def test_workspace():
    root = tools.workspace_root()
    if not root:
        return {"ok": False, "error": "Workspace folder is empty or does not exist."}
    r = tools.execute("list_dir", {"path": "."}) if "list_dir" in tools.enabled_tools() else {"ok": True, "result": "(read disabled)"}
    return {"ok": r["ok"], "path": str(root), "tools": tools.enabled_tools(), "listing": r.get("result", r.get("error"))}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if TOKEN and ws.query_params.get("token") != TOKEN:
        await ws.close(code=4401)
        return
    await ws.accept()
    log.info("UI connected")
    send_lock = asyncio.Lock()
    pending: dict[str, asyncio.Future] = {}
    turn_task: asyncio.Task | None = None

    async def emit(msg: dict) -> None:
        async with send_lock:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception as e:
                log.debug("emit failed (%s): client probably gone", e)

    async def confirm(tool: str, desc: str) -> bool:
        cid = agent.new_id()
        fut = asyncio.get_running_loop().create_future()
        pending[cid] = fut
        await emit({"type": "confirm", "id": cid, "tool": tool, "description": desc})
        try:
            return await asyncio.wait_for(fut, timeout=90)
        except asyncio.TimeoutError:
            log.warning("Confirmation %s timed out -> denied", cid)
            return False
        finally:
            pending.pop(cid, None)

    await emit({"type": "hello", "workspace": str(tools.workspace_root() or ""), "tools": tools.enabled_tools()})
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "chat":
                if turn_task and not turn_task.done():
                    turn_task.cancel()
                    await asyncio.gather(turn_task, return_exceptions=True)
                text = str(msg.get("text", "")).strip()
                if text:
                    turn_task = asyncio.create_task(agent.run_turn(msg.get("session_id") or "default", text, emit, confirm))
            elif kind == "stop":
                if turn_task and not turn_task.done():
                    turn_task.cancel()
                    await emit({"type": "stopped"})
            elif kind == "confirm_response":
                fut = pending.get(msg.get("id"))
                if fut and not fut.done():
                    fut.set_result(bool(msg.get("allow")))
            else:
                log.warning("Unknown WS message type: %r", kind)
    except WebSocketDisconnect:
        log.info("UI disconnected")
    except Exception:
        log.exception("WebSocket loop crashed")
    finally:
        if turn_task and not turn_task.done():
            turn_task.cancel()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", default=None)
    a = ap.parse_args()
    if a.data_dir:
        DATA_DIR = Path(a.data_dir)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_config=None, log_level="warning")
