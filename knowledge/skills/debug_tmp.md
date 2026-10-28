# Skill: debug (temporary)

**Source:** `backend/skills/debug_tmp.py`
**Knowledge doc:** `knowledge/skills/debug_tmp.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `debug_test_llm` | `debug_test_llm(tier='fast')   # test one brain tier (fast/mid/heavy)` | misc | Testing the fast model tier |
| `debug_test_tts` | `debug_test_tts(text='Crystal voice check. Can you hear me?')   # test TTS synthesis` | misc | Testing TTS with N characters |
| `debug_test_workspace` | `debug_test_workspace()   # check the workspace folder is reachable` | misc | Testing the workspace folder |

## What it does

Temporary debug skills that mirror the backend's `/api/test/*` endpoints. Each reports OK or
FAILED with a clear message, so you can test each pipeline part in isolation.

- `debug_test_llm(tier)` — chats with one Ollama tier (fast / mid / heavy) and reports the
  reply and elapsed time, or the failure reason.
- `debug_test_tts(text)` — synthesizes one sentence with Phonon and reports byte count and
  time, or skipped/failed. Skipped if `voice.engine` is not `phonon`.
- `debug_test_workspace()` — checks the workspace folder is reachable via `execute("list_dir", {"path": "."})`.

## Permission

`misc` — diagnostic only, no workspace folder needed (workspace test reports failure if none
set rather than erroring hard).

## Notes

Marked "(temporary)" — intended for development. Turn off or remove before shipping.

## Implementation

Uses `ollama.chat_stream`, `phonon.synthesize`, `tools.execute("list_dir", ...)`, and
`tools.workspace_root()`. Async generators are drained with an inner `asyncio.run()`.
