# Skill template

**Source:** `backend/skills/_template.py`
**Knowledge doc:** `knowledge/skills/_template.md`

## What it is

A worked example skill file. Files starting with `_` are never loaded by the backend, so this
file is a reference only — copy it, rename (no leading underscore), edit, and use it as the
basis for new skills.

## What it demonstrates

- A function `word_count(path)` that reads a file with `tools._safe(path)` and returns
  "N words, M lines".
- A `register(register_tool)` function that calls `register_tool(name=..., signature=...,
  perm=..., fn=..., describe=...)`.

## Rules of thumb (from the template docstring)

- Return small outputs (the model has a small context)
- Never trust the arguments
- Use `tools._safe(path)` for any file path so the workspace sandbox still applies
- Raise `ToolError("clear message")` to refuse or fail politely

## How to create a new skill from this template

1. Copy `backend/skills/_template.py` → `backend/skills/your_skill.py` (no leading `_`)
2. Write your function (kwargs in, short string out)
3. Implement `register(register_tool)` calling `register_tool(...)` for each tool
4. Settings → Tools & diagnostics → "Reload skills" (no restart)
