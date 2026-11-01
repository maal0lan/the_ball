# Skill: folder_profile

**Source:** `backend/skills/folder_profile.py`
**Knowledge doc:** `knowledge/skills/folder_profile.md`

## Tools registered

| Tool | Signature | Perm | Confirm? | Description |
|------|-----------|------|----------|-------------|
| `folder_profile` | `folder_profile(path=".")` | read | No | Profiling folder {path} |

## What it does

Answers "what does this folder contain?" with a rich one-shot read-only profile of a workspace folder:

- total item count, split into files vs folders
- total size (human-readable, B → TB)
- breakdown by file extension (top 6)
- largest files (top 5, with sizes)
- newest files (top 5, with modification times)

Only the active workspace folder is searchable — paths outside it are rejected by the `_safe()` sandbox.

## Example input / output

`folder_profile(path=".")` (workspace root):

```
Folder profile: .
  items: 47 total  (32 files, 15 folders)
  size: 3.2 MB
  by extension:
    .py: 18
    .md: 6
    .json: 4
    (no extension): 3
    .css: 1
  largest files:
    1.1 MB  backend/server.py
    890 KB  renderer/ball.js
  newest files:
    2026-10-31 09:42  knowledge/skills/folder_profile.md
```

## Permission

`read` — needs the workspace folder and the "Allow reading" switch on in Settings → Agent. No confirmation prompt (read-only).

## Implementation

Walks the folder with `os.walk`, respects `agent.ignore` patterns, skips symlinks when `agent.followSymlinks` is off, and caps at the workspace root. Output is kept small so it fits in the model's context.

## Trust

This skill loads only after the user trusts it (Settings → Tools & diagnostics → "Trust this skill"). The trust is tied to the file's SHA-256; editing the file withdraws trust.
