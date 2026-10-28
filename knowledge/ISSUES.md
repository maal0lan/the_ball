# Skill issues / gaps

Recorded 2026-10-28 while auditing `backend/skills/`.

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

## Missing skills

None found. Every skill the docs and tests expect is implemented.

## Future skills (tracked here, not filed as GitHub issues — sandbox denies external writes)

- Speech-to-text / voice-in (docs §14.5)
- History browser UI (REST exists in `backend/history.py`; no UI yet)

See `room-for-improvement/README.md` for longer-term improvement notes.

## How to file real issues

GitHub issue creation (`gh issue create`) is blocked in this sandbox, so issues are recorded
here instead. When you have GitHub access, create issues on
`github.com/maal0lan/the_ball` referencing branch `feature/backend-skills-diagnostics`.
