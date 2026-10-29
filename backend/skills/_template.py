"""
SKILL TEMPLATE — copy this file, rename it (no leading underscore), edit, then use
Settings → Tools & diagnostics → "Reload skills". Files starting with "_" are never loaded.

A skill file only needs a  register(register_tool)  function. Call register_tool once per tool:

  name       the name the model writes:  <tool>{"name": "<name>", "args": {...}}</tool>
  signature  one line shown to the model. Keep it short; a trailing  # comment  helps small models.
  perm       "read" | "write" | "delete" | "exec" | "net" | "misc"
               - read/write/delete/exec need the workspace folder and the matching switch in Settings → Agent
               - net  needs "Allow network" ; misc needs nothing (only for harmless things)
               - write/delete/exec/net ask for Allow/Deny first by default
  fn         your function. Receives the model's args as keyword arguments, returns a short STRING.
             Raise ToolError("clear message") to refuse or fail politely.
  confirm    optional, default False: True = ALWAYS ask Allow/Deny first, whatever the perm. Use it for anything that
             deletes, restarts, sends, spends, or changes settings — even if you filed it under "misc".
  describe   optional: args -> sentence shown in the UI / confirmation card (make it specific!)

TRUST: a skill file only loads after you trust it (Settings → Tools & diagnostics → "Trust this skill"). The trust
is tied to the file's SHA-256, so editing the file withdraws it; while developing, set Settings → Agent → Skill trust = warn.
Want to give the model instructions instead of code? Use a markdown skill: see _template.md.

Rules of thumb: return small outputs (the model has a small context); never trust the arguments;
use tools._safe(path) for any file path so the workspace sandbox still applies.
"""
from tools import ToolError, _safe   # noqa: F401  (ToolError / _safe are what skills usually need)


def word_count(path: str) -> str:
    text = _safe(path).read_text("utf-8", "replace")
    return f"{len(text.split())} words, {len(text.splitlines())} lines"


def register(register_tool):
    register_tool(
        name="word_count",
        signature="word_count(path)   # count words and lines in a text file",
        perm="read",
        fn=word_count,
        describe=lambda a: f"Counting words in {a.get('path', '?')}",
    )
