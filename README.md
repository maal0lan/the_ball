# Crystal — a local AI agent that lives in a glass ball on your desktop

A frameless, transparent crystal ball floats on your desktop and **refracts whatever is behind it**.
Click it, type, press Enter: a local LLM (via Ollama) answers, a local TTS model speaks every reply,
and the agent can read/search/edit files in **one folder you choose**. Everything runs on your machine.

```
Electron (ball window, settings window, debug console)  <—WebSocket/HTTP on 127.0.0.1—>  Python backend
   WebGL glass shader · screen capture · tray · hotkey        Ollama LLM · Phonon/system TTS · file tools · SQLite
```

## Quick start

1. Install **Node.js 20+**, **Python 3.11+**, and **[Ollama](https://ollama.com)**.
2. Run setup  
   Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`  
   macOS/Linux: `bash scripts/setup.sh`
3. Pull the brains: `ollama pull phi` · `ollama pull mistral` · (fast model: see Settings → Brain)
4. Accept the licence for `gradium/phonon-40m-en` on Hugging Face, then `hf auth login`
5. `npm start`

Click the ball → type → Enter. Right-click the ball (or use the tray icon) for the menu.
Hotkey: **Ctrl/Cmd + Alt + Space**. A **debug console** opens automatically and shows every log line and error from every process.

**Read [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)** for architecture, every setting, troubleshooting and how to extend it.
