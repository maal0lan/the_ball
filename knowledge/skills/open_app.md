# Skill: open_app

**Source:** `backend/skills/open_app.py`
**Knowledge doc:** `knowledge/skills/open_app.md`

## Tools registered

| Tool | Signature | Perm | Confirm? | Description |
|------|-----------|------|----------|-------------|
| `open_app` | `open_app(target)   # open an app, file, or URL` | misc | Yes | Opening {target} |

## What it does

Opens apps, files, folders, or URLs on the local machine. Also understands
search-style requests so the model can say things like "open this song on
youtube" and the skill will open a YouTube search results page.

| Input | What happens |
|-------|--------------|
| `notepad` | Launches Notepad via `os.startfile` |
| `https://youtube.com` | Opens in the default browser |
| `www.example.com` | Opens `https://www.example.com` |
| `open this song on youtube` | Opens YouTube search for "this song" |
| `search for weather` | Opens a Google search for "weather" |
| `C:\Windows\System32\calc.exe` | Launches Calculator |

## Permission

`misc` — no workspace folder needed (it launches apps / opens URLs, not files
inside the workspace). However it *can* start any local program, so
`confirm=True` is set: the user always sees an Allow/Deny prompt before anything
is opened.

## How search works

Phrases containing "youtube" trigger a YouTube results page. Phrases starting
with "search " or "google " trigger a Google search. Everything else is treated
as a direct app name, file path, folder, or URL.

## Implementation

Uses `webbrowser.open()` for URLs, `os.startfile()` for local apps/files, and
`subprocess.Popen()` as a fallback for command-style launches. Search queries
are URL-encoded with `urllib.parse.quote_plus`.

## Trust

This skill loads only after the user trusts it
(Settings → Tools & diagnostics → "Trust this skill"). The trust is tied to the
file's SHA-256; editing the file withdraws trust.

## Rules of thumb

- Return small outputs (the model has a small context)
- Never trust the arguments — validate before acting
- Raise `ToolError("clear message")` to refuse politely
