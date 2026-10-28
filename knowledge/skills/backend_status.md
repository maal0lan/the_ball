# Skill: backend status

**Source:** `backend/skills/backend_status.py`
**Knowledge doc:** `knowledge/skills/backend_status.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `backend_status` | `backend_status()   # backend process status: Ollama, tiers, TTS, workspace` | misc | Checking backend status |
| `backend_restart` | `backend_restart(confirm='no')   # exit so the supervisor restarts the backend` | misc | RESTARTING the backend process |

## What it does

- `backend_status()` — read-only dump of backend process status: uptime, Ollama reachability
  and model count, LLM tiers (fast/mid/heavy), TTS engine/model/loaded state, workspace
  folder, history DB, and installed models.
- `backend_restart(confirm='yes')` — exits the Python process (`os._exit(0)`) so the
  Electron supervisor (`backend.js`) restarts it. Same as a crash restart. Refuses without
  `confirm='yes'`.

Example `backend_status()` output:

```
Uptime: 120s
Ollama: http://127.0.0.1:11434 — reachable, 2 model(s)
Tiers: fast=LiquidAI/lfm2.5-350m:latest, mid=phi, heavy=mistral
TTS: engine=phonon model=gradium/phonon-40m-en loaded=True
Workspace: C:\...\workspace
History DB: C:\...\chat_history.db
Installed models: phi, mistral
```

## Permission

`misc`. `backend_restart` requires `confirm='yes'` (it kills the backend process).

## Implementation

`backend_status` uses `ollama.list_models()`, `config.settings`, `tts.phonon.loaded`,
`tools.workspace_root()`, and `history._DB`. `backend_restart` calls `os._exit(0)`.
