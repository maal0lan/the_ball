# Skill issues / gaps

Recorded 2026-10-28 while auditing `backend/skills/`. Last updated 2026-10-28.

## Skills that exist (no issue)

All skills referenced in `docs/DOCUMENTATION.md` §9.5 and in `tests/test_backend.py` are
present in `backend/skills/`:

| Skill file | Status |
|------------|--------|
| `get_time.py` | ✅ exists |
| `system_info.py` | ✅ exists |
| `fetch_url.py` | ✅ exists |
| `settings_read.py` | ✅ exists |
| `memory_history.py` | ✅ exists |
| `backend_status.py` | ✅ exists |
| `debug_tmp.py` | ✅ exists |
| `tools_diagnostics.py` | ✅ exists |
| `_template.py` | ✅ exists (template, not loaded) |

## Missing skills — CLOSED

None found. Every skill the docs and tests expect is implemented.
**Status: cleared — closed 2026-10-28.** No GitHub issue filed (sandbox denies external
writes); recorded here instead.

## Changes made on `feature/backend-skills-complete` (2026-10-28)

| Area | File(s) | What changed |
|------|---------|--------------|
| Tolerant tool-call parsing | `backend/agent.py` | Real models (Mistral 7B) don't write `<tool>…</tool>` exactly. `ToolStreamFilter` now accepts `<tool`, `[tool`, code fences, `{"name"`, `{"function"`, `{"tool"` openers; finds the first complete JSON object (`name` + `args`/`arguments`/`parameters`, arguments may be a JSON string); accepts raw newlines in strings (`strict=False`). Ordinary text / code blocks / non-tool JSON stream through untouched. Cut-off calls are flagged `suspect` and the model is told to resend valid JSON. |
| Token budget for tools | `backend/agent.py`, `shared/settings-schema.json` | Writing a file puts its whole content inside the tool call, so tool replies use `max(llm.maxTokens, agent.toolMaxTokens)` (new setting `agent.toolMaxTokens`, default 1500, range 256–8192). |
| Per-skill confirm flag | `backend/tools.py`, `backend/skills/_template.py` | `tools.register(..., confirm=...)` — True always asks Allow/Deny regardless of perm. `_template.py` documents it (use for anything that deletes/restarts/sends/spends/changes settings). |
| Why a tool is inactive | `backend/tools.py` | New `why_inactive(name)` returns a plain-English reason (file tools off, skills disabled, no workspace, allow switch off, disabled skill). `list_skills()` now returns `reason` and `confirm` per tool; the UI shows "inactive because: …". |
| Simpler permission gating | `backend/tools.py` | Removed the per-tool `agent.tool.<name>` allow/deny/ask settings (too granular). `misc` tools are no longer special-cased past `agent.enabled` — gating is now uniform. `needs_confirmation()` uses the per-skill `confirm` flag. |
| Better error message | `backend/tools.py` | Unknown/disabled tool now lists the tools that *are* available so the model can self-correct. |
| Backend status endpoint | `backend/server.py` | `/api/status` now also reports `workspace.configured` and each inactive tool's `reason`. |
| UI | `renderer/settings.js` | Skills list shows `, asks first` for confirm-required tools and "inactive because: <reason>" for inactive ones. |
| Docs | `docs/DOCUMENTATION.md` | §9.2 call format explains the forgiving parser + token budget; settings reference now 135 settings; new troubleshooting rows for cut-off calls and models chatting about files instead of creating them. |
| Tests | `tests/test_backend.py`, `tests/e2e_mock.py` | New tests: `why_inactive` reasons, `confirm` flag forces confirmation, all real model formats recognised (parametrised), prose kept + call hidden, normal code block released, non-tool JSON is just text, cut-off call flagged suspect, bare tool name resolves, unknown tool error lists available tools, prompt without workspace doesn't crash. E2E now covers Mistral-style broken format + cut-off call → file really created on disk, and raw tool calls never leak into chat/TTS. |

## Future skills (tracked here, not filed as GitHub issues — sandbox denies external writes)

- Speech-to-text / voice-in (docs §14.5)
- History browser UI (REST exists in `backend/history.py`; no UI yet)

See `room-for-improvement/README.md` for longer-term improvement notes.

## How to file real issues

GitHub issue creation (`gh issue create`) is blocked in this sandbox, so issues are recorded
here instead. When you have GitHub access, create issues on
`github.com/maal0lan/the_ball` referencing branch `feature/backend-skills-complete`.


## Skill trust and instruction skills — branch `feature/skill-trust` (2026-10-29)

Addresses the "plugin skills run with full privileges, nothing verifies them" issue. **Written but not yet evaluated.**

| Acceptance criterion | Where |
|---|---|
| Unsigned/unknown skill files show a warning in Tools & diagnostics | `renderer/settings.js` `showSkills()`; `tools.SKILL_FILES`; `/api/skills`, `/api/status` → `skills.needs_review` |
| Option to trust a skill by hash/path | "Trust this skill" button → setting `agent.trustedSkills` `{file: sha256}`; bundled hashes in `backend/skills_manifest.json` |
| No auto-loading of skills from outside `backend/skills/` | `tools.skills_dir()` ignores `CRYSTAL_SKILLS_DIR` unless `CRYSTAL_ALLOW_EXTERNAL_SKILLS=1`; symlinks outside skipped in `skill_trust.discover()` |
| Documented risk in docs | `docs/DOCUMENTATION.md` §9.5, §16, §19 |

Also added: markdown "instruction skills" (`*.md`, `<name>/SKILL.md`, read via `use_skill(name)`), hash-then-run-the-same-bytes
loading, a ban on skills replacing built-in tools, and agent write/delete protection for the skills folder + manifest.

Known gaps / follow-ups: trust list lives in plain settings (an imported settings file could carry it); no signatures
(hash proves "the file you reviewed", not "safe"); an agent with `run_command` rights over the Crystal folder could still edit
the manifest; `debug_tmp.py` is still bundled and trusted.
