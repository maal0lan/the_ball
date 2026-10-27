"""End-to-end smoke test with a fake Ollama. Run:  python tests/e2e_mock.py"""
import asyncio, json, os, subprocess, sys, tempfile, time, threading
from pathlib import Path
import httpx, websockets, uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

mock = FastAPI()
@mock.get("/api/tags")
async def tags(): return {"models": [{"name": "phi"}]}
@mock.post("/api/chat")
async def chat(body: dict):
    msgs = body["messages"]
    if body["model"] == "missing": return StreamingResponse(iter([b""]), status_code=404)
    saw_result = any("<tool_result>" in m["content"] for m in msgs)
    text = ("I read it. The note says hello world. It also has a secret plan." if saw_result else
            'Sure, checking. <tool>{"name":"read_file","args":{"path":"a.md"}}</tool>')
    async def gen():
        for i in range(0, len(text), 7):
            yield (json.dumps({"message": {"content": text[i:i+7]}, "done": False}) + "\n").encode()
        yield (json.dumps({"done": True}) + "\n").encode()
    return StreamingResponse(gen(), media_type="application/x-ndjson")

threading.Thread(target=lambda: uvicorn.run(mock, port=11999, log_level="error"), daemon=True).start()
time.sleep(1)

ws_dir = tempfile.mkdtemp(); Path(ws_dir, "a.md").write_text("hello world, secret plan")
data = tempfile.mkdtemp()
env = {**os.environ, "CRYSTAL_TOKEN": "t0k", "PYTHONUNBUFFERED": "1"}
srv = subprocess.Popen([sys.executable, "server.py", "--port", "8799", "--data-dir", data],
                       cwd=Path(__file__).parent.parent / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

async def main():
    H = {"Authorization": "Bearer t0k"}
    async with httpx.AsyncClient() as c:
        for _ in range(40):
            try:
                if (await c.get("http://127.0.0.1:8799/health")).status_code == 200: break
            except Exception: await asyncio.sleep(0.25)
        assert (await c.get("http://127.0.0.1:8799/api/status")).status_code == 401, "auth must be enforced"
        r = await c.post("http://127.0.0.1:8799/api/settings", headers=H, json={
            "llm.host": "http://127.0.0.1:11999", "llm.mode": "heavy", "llm.model.heavy": "phi",
            "voice.engine": "system", "agent.workspace": ws_dir, "agent.allowWrite": True, "llm.warmup": False})
        print("settings changed:", r.json()["changed"][:3], "...")
        print("status:", (await c.get("http://127.0.0.1:8799/api/status", headers=H)).json()["workspace"])
        print("test/llm:", (await c.post("http://127.0.0.1:8799/api/test/llm", headers=H, json={"tiers": ["heavy"]})).json())
    async with websockets.connect("ws://127.0.0.1:8799/ws?token=t0k") as ws:
        print("hello:", json.loads(await ws.recv())["tools"])
        await ws.send(json.dumps({"type": "chat", "session_id": "s", "text": "read a.md for me"}))
        shown, spoken = "", []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if m["type"] == "token": shown += m["text"]
            elif m["type"] == "speak": spoken.append(m["text"])
            elif m["type"] in ("tool_call", "tool_result", "error"): print(m)
            elif m["type"] == "done": print("done:", m["model"], m["seconds"]); break
        print("shown :", shown); print("spoken:", spoken)
        assert "<tool>" not in shown and "hello world" in shown and spoken
        # missing model error path
        r = httpx.post("http://127.0.0.1:8799/api/settings", headers=H, json={"llm.model.heavy": "missing"})
        await ws.send(json.dumps({"type": "chat", "session_id": "s", "text": "hi"}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if m["type"] == "error": print("error path:", m["message"]); break
    print("E2E OK")

try: asyncio.run(main())
finally:
    srv.terminate(); out = srv.stdout.read()[-1500:]; print("---- backend log tail ----\n" + out)
