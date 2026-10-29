# Knowledge base: skills

Drop-in plugin tools for the Crystal backend live in `backend/skills/`. This folder holds a
markdown "dump" (reference doc) for every skill file, so anyone can see what each skill does,
which tools it registers, its permission level, and where its source file is.

## How skills work

A skill is a Python file in `backend/skills/` that defines a `register(register_tool)` function.
The backend loads every non-underscore `*.py` file at startup (and on "Reload skills" from
Tools & diagnostics). See `backend/skills/_template.py` for the canonical example.

Permission levels:
- `read` / `write` / `delete` / `exec` — need a workspace folder + their Settings switch
- `net` — needs "Allow network access"
- `misc` — harmless, no workspace needed

Write/delete/exec/net ask for Allow/Deny confirmation by default.

## Trust and instruction skills

Skill files must be trusted before they load (bundled hashes in `backend/skills_manifest.json`, your own in the
`agent.trustedSkills` setting). Besides Python skills there are markdown *instruction skills* (`*.md` or
`<name>/SKILL.md`) that the model reads through `use_skill(name)`. Full details: `docs/DOCUMENTATION.md` §9.5.
After editing a bundled skill run `python scripts/update_skill_manifest.py`.

## Skill files

| Skill file | Tools registered | Perm | Source |
|------------|------------------|------|--------|
| `get_time.py` | `get_time()` | misc | [backend/skills/get_time.py](../backend/skills/get_time.py) |
| `system_info.py` | `system_info()` | misc | [backend/skills/system_info.py](../backend/skills/system_info.py) |
| `fetch_url.py` | `fetch_url(url)` | net | [backend/skills/fetch_url.py](../backend/skills/fetch_url.py) |
| `settings_read.py` | `settings_read(section='')` | misc | [backend/skills/settings_read.py](../backend/skills/settings_read.py) |
| `memory_history.py` | `history_list_sessions`, `history_read_session`, `history_latest_session`, `history_prune`, `history_delete_session` | misc | [backend/skills/memory_history.py](../backend/skills/memory_history.py) |
| `backend_status.py` | `backend_status()`, `backend_restart()` | misc | [backend/skills/backend_status.py](../backend/skills/backend_status.py) |
| `debug_tmp.py` | `debug_test_llm(tier)`, `debug_test_tts(text)`, `debug_test_workspace()` | misc | [backend/skills/debug_tmp.py](../backend/skills/debug_tmp.py) |
| `tools_diagnostics.py` | `tools_list_skills()`, `tools_reload_skills()`, `models_refresh()` | misc | [backend/skills/tools_diagnostics.py](../backend/skills/tools_diagnostics.py) |
| `open_app.py` | `open_app(target)` | misc | [backend/skills/open_app.py](../backend/skills/open_app.py) |
| `_template.py` | (template only, not loaded) | — | [backend/skills/_template.py](../backend/skills/_template.py) |

## Verification status

All skills listed above exist and are implemented in `backend/skills/`. No missing skills were found, so no issues were filed.

Related: `room-for-improvement/` holds longer-term improvement notes (speech-to-text, history browser UI, etc.).