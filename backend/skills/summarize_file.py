"""
summarize_file: "summarize this" — read a text file and return a compact
summary: line/word/char count, detected type, plus a head/tail excerpt.
Read-only, respects the workspace sandbox and size limits.

Knowledge doc: ../knowledge/skills/summarize_file.md
"""
from pathlib import Path

from tools import ToolError, _safe, _read_text, _rel, _ext_ok


def summarize_file(path: str) -> str:
    """Summarize a text file: size, counts, type, and a head/tail excerpt."""
    p = Path(_safe(path))
    if not p.is_file():
        raise ToolError(f"'{path}' is not a file.")
    if not _ext_ok(p):
        raise ToolError(f"Extension '{p.suffix}' is not allowed (Settings → Agent).")

    text = _read_text(p)
    lines = text.splitlines()
    words = len(text.split())
    chars = len(text)

    kind = {
        ".py": "Python source", ".md": "Markdown", ".txt": "Plain text",
        ".json": "JSON", ".html": "HTML", ".css": "CSS", ".js": "JavaScript",
        ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
        ".csv": "CSV", ".log": "Log", ".yaml": "YAML", ".yml": "YAML",
        ".toml": "TOML", ".ini": "INI", ".cfg": "INI",
    }.get(p.suffix.lower(), f"{p.suffix or 'no-extension'} file")

    head = "\n".join(lines[:6])
    tail = "\n".join(lines[-6:]) if len(lines) > 6 else ""
    excerpt = head + (("\n…\n" + tail) if tail else "")

    lines_out = [
        f"Summary of {_rel(p)}",
        f"  type: {kind}",
        f"  lines: {len(lines)}  words: {words}  chars: {chars}",
        f"  excerpt:",
    ]
    for ln in excerpt.splitlines():
        lines_out.append(f"    {ln}")
    return "\n".join(lines_out)


def register(register_tool):
    register_tool(
        name="summarize_file",
        signature="summarize_file(path)   # read a file and return a compact summary",
        perm="read", fn=summarize_file,
        describe=lambda a: f"Summarizing {a.get('path', '?')}",
    )
