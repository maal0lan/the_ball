# Skill: find_any

**Source:** `backend/skills/find_any.py`
**Knowledge doc:** `knowledge/skills/find_any.md`

## Tools registered

| Tool | Signature | Perm | Confirm? | Description |
|------|-----------|------|----------|-------------|
| `find_any` | `find_any(pattern, path=".")` | read | No | Finding “{pattern}” in {path} |

## What it does

Answers "find this folder / file" — a recursive search for files AND folders whose name matches a pattern, anywhere under the workspace.

The `pattern` can be:
- a glob: `*.md`, `notes*`, `*.py` (uses `*` `?` `[]` wildcards)
- a plain substring: `notes`, `config`, `tmp` (matched case-insensitively)

Each result is prefixed `[file]` or `[dir]` so you can tell files from folders. Results are capped at 200.

Differs from the built-in `search_files` (filename glob only, files only): `find_any` matches folders too and accepts plain substrings, not just globs.

## Example input / output

`find_any(pattern="*.md")`:

```
[file] README.md
[file] knowledge/ISSUES.md
[file] knowledge/skills/README.md
[file] knowledge/skills/folder_profile.md
```

`find_any(pattern="notes")`:

```
[dir]  project/notes
[file] project/notes/todo.md
[file] meeting_notes.txt
```

## Permission

`read` — needs the workspace folder and the "Allow reading" switch on. No confirmation prompt (read-only).

## Trust

This skill loads only after the user trusts it (Settings → Tools & diagnostics → "Trust this skill"). The trust is tied to the file's SHA-256; editing the file withdraws trust.
