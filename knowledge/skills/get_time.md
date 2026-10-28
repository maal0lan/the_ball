# Skill: get_time

**Source:** `backend/skills/get_time.py`
**Knowledge doc:** `knowledge/skills/get_time.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `get_time` | `get_time()   # current local date and time` | misc | Checking the time |

## What it does

Returns the current local date and time as a short string, e.g.:

```
Wednesday 28 October 2026, 10:45:32 UTC
```

Small models cannot know the current date/time, so this skill lets the assistant answer
"What time is it?" and "What's today's date?" accurately.

## Permission

`misc` — harmless, no workspace folder needed, no confirmation required.

## Implementation

The function uses `datetime.now().astimezone()` and formats with `strftime`. It takes no arguments.
