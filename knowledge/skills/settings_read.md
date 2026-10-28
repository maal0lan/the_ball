# Skill: settings_read

**Source:** `backend/skills/settings_read.py`
**Knowledge doc:** `knowledge/skills/settings_read.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `settings_read` | `settings_read(section='')   # read-only settings dump for a section (brain, voice, agent, …)` | misc | Reading settings section "all" |

## What it does

Dumps the agent's live settings as JSON so the model can answer questions like:
- "What model am I using?" (`section=brain`)
- "Is network access on?" (`section=agent`)
- "What workspace is set?" (`section=agent`)

Pass a section prefix (e.g. `brain`, `voice`, `agent`, `history`) or leave empty for all
settings. Unknown sections return "No settings found…".

Example:

```
settings_read(section="brain")
```
```json
{
  "llm.mode": "auto",
  "llm.model.fast": "LiquidAI/lfm2.5-350m:latest",
  "llm.model.mid": "phi",
  "llm.model.heavy": "mistral"
}
```

## Permission

`misc` — read-only, no workspace folder needed, no confirmation required. No settings
write access is exposed from a skill (that would be dangerous).

## Implementation

Reads from the live `config.settings` object (loaded once from
`shared/settings-schema.json`, updated live via `POST /api/settings`).
