# Skill: summarize_file

**Source:** `backend/skills/summarize_file.py`
**Knowledge doc:** `knowledge/skills/summarize_file.md`

## Tools registered

| Tool | Signature | Perm | Confirm? | Description |
|------|-----------|------|----------|-------------|
| `summarize_file` | `summarize_file(path)` | read | No | Summarizing {path} |

## What it does

Answers "summarize this" — reads a text file and returns a compact summary:

- detected file type (by extension)
- line count, word count, character count
- a head/tail excerpt (first 6 lines, last 6 lines if longer)

Read-only. Respects the workspace sandbox, `agent.allowedExtensions`, `agent.maxFileSizeMB`, and `agent.maxReadChars`.

## Example input / output

`summarize_file(path="README.md")`:

```
Summary of README.md
  type: Markdown
  lines: 42  words: 310  chars: 1980
  excerpt:
    # Crystal
    A local AI agent: an Electron ball UI + Python FastAPI backend.
    …
    ## Features
    - Model provider + workspace switching from the ball UI
    - Plugin skills with trust verification
```

## Permission

`read` — needs the workspace folder and the "Allow reading" switch on. No confirmation prompt (read-only).

## Trust

This skill loads only after the user trusts it (Settings → Tools & diagnostics → "Trust this skill"). The trust is tied to the file's SHA-256; editing the file withdraws trust.
