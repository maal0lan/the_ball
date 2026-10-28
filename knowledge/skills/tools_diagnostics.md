# Skill: tools & diagnostics

**Source:** `backend/skills/tools_diagnostics.py`
**Knowledge doc:** `knowledge/skills/tools_diagnostics.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `tools_list_skills` | `tools_list_skills()   # list every registered tool and its state` | misc | Listing registered skills and tools |
| `tools_reload_skills` | `tools_reload_skills()   # reload all backend/skills/*.py files` | misc | Reloading skill files |
| `models_refresh` | `models_refresh()   # refresh the Ollama model list` | misc | Refreshing the Ollama model list |

## What it does

- `tools_list_skills()` — lists every registered tool with its state (active/error), permission,
  source, and signature. Errors (skill files that failed to load) are shown with `✗`.
- `tools_reload_skills()` — reloads all `backend/skills/*.py` files and reports how many tools
  were loaded from which directory.
- `models_refresh()` — refreshes the Ollama model list via `ollama.list_models()` and reports
  the count and names, or a "No Ollama models found" hint.

## Permission

`misc` — diagnostic only, no workspace folder needed.

## Implementation

Uses `tools.list_skills()`, `tools.load_skills()`, `tools.skills_dir()`, and
`ollama.list_models()` (async, drained with `asyncio.run()`).
