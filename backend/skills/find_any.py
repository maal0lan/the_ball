"""
find_any: "find this folder / file" — recursive search for files AND folders
matching a name pattern (glob or substring) anywhere under the workspace.
Returns relative paths with a type marker so you can tell files from folders.
Read-only.

Knowledge doc: ../knowledge/skills/find_any.md
"""
import fnmatch
import os
from pathlib import Path

from tools import ToolError, _safe, _ignored, _rel


def find_any(pattern: str, path: str = ".") -> str:
    """Find files and folders whose name matches `pattern`.

    Args:
        pattern: name glob (e.g. "*.md", "notes*") or plain substring to match.
        path: folder to search under (default "." = workspace root).
    """
    root = Path(_safe(path))
    if not root.is_dir():
        raise ToolError(f"'{path}' is not a folder.")

    cap = 200
    hits: list[str] = []
    pat = str(pattern).strip()
    if not pat:
        raise ToolError("Give me a name pattern to search for, e.g. '*.md' or 'notes'.")
    is_glob = any(ch in pat for ch in "*?[]")

    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not _ignored(d)]
        # folders
        for d in dns:
            name = d.lower()
            match = fnmatch.fnmatch(name, pat.lower()) if is_glob else pat.lower() in name
            if match:
                hits.append(f"[dir]  {_rel(Path(dp) / d)}")
                if len(hits) >= cap:
                    return "\n".join(hits) + f"\n…[result limit reached ({cap})]"
        # files
        for fn in fns:
            if _ignored(fn):
                continue
            name = fn.lower()
            match = fnmatch.fnmatch(name, pat.lower()) if is_glob else pat.lower() in name
            if match:
                hits.append(f"[file] {_rel(Path(dp) / fn)}")
                if len(hits) >= cap:
                    return "\n".join(hits) + f"\n…[result limit reached ({cap})]"

    return "\n".join(hits) if hits else f"No files or folders matched “{pat}” under {_rel(root)}."


def register(register_tool):
    register_tool(
        name="find_any",
        signature='find_any(pattern, path=".")   # find files AND folders by name pattern, recursively',
        perm="read", fn=find_any,
        describe=lambda a: f"Finding “{a.get('pattern', '?')}” in {a.get('path', '.')}",
    )
