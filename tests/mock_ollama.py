"""Tiny fake Ollama for UI testing:  python tests/mock_ollama.py [port]"""
import json, sys, asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn
app = FastAPI()
@app.get("/api/tags")
async def tags(): return {"models": [{"name": "phi"}, {"name": "mistral"}]}
@app.post("/api/generate")
async def gen(body: dict): return {"done": True}
@app.post("/api/chat")
async def chat(body: dict):
    text = "Sure! I can hear you loud and clear. This reply is streaming one little chunk at a time, just like a real model would."
    async def g():
        for i in range(0, len(text), 6):
            await asyncio.sleep(0.05)
            yield (json.dumps({"message": {"content": text[i:i+6]}, "done": False}) + "\n").encode()
        yield (json.dumps({"done": True}) + "\n").encode()
    return StreamingResponse(g(), media_type="application/x-ndjson")
if __name__ == "__main__":
    uvicorn.run(app, port=int(sys.argv[1]) if len(sys.argv) > 1 else 11434, log_level="error")
