"""
Sandboxed file tools for the agent. EVERY path is resolved and must stay inside
the workspace folder chosen in Settings. Returns plain dicts; never raises to the caller.
"""
import fnmatch
import logging
import os
from pathlib import Path

from config import settings

log = logging.getLogger("backend.tools")

TOOL_SIGNATURES = {
    "list_dir": 'list_dir(path=".")',
    "read_file": "read_file(path)",
    "search_files": "search_files(pattern)   # file-name glob such as *.md",
    "grep": 'grep(text, path=".")   # find text inside files',
    "write_file": "write_file(path, content, append=false)",
    "make_dir": "make_dir(path)",
    "delete_path": "delete_path(path)",
}
READ_TOOLS = {"list_dir", "read_file", "search_files", "grep"}
WRITE_TOOLS = {"write_file", "make_dir"}
DELETE_TOOLS = {"delete_path"}


class ToolError(Exception):
    pass


def workspace_root() -> Path | None:
    w = str(settings.get("agent.workspace") or "").strip()
    if not w:
        return None
    p = Path(w).expanduser()
    return p.resolve() if p.is_dir() else None


def enabled_tools() -> list[str]:
    if not settings.get("agent.enabled") or workspace_root() is None:
        return []
    out: list[str] = []
    if settings.get("agent.allowRead"):
        out += sorted(READ_TOOLS, key=list(TOOL_SIGNATURES).index)
    if settings.get("agent.allowWrite"):
        out += sorted(WRITE_TOOLS, key=list(TOOL_SIGNATURES).index)
    if settings.get("agent.allowDelete"):
        out += sorted(DELETE_TOOLS, key=list(TOOL_SIGNATURES).index)
    return out


def needs_confirmation(tool: str) -> bool:
    return bool(settings.get("agent.confirmWrites")) and tool in (WRITE_TOOLS | DELETE_TOOLS)


def _ignored(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in settings.csv("agent.ignore"))


def _safe(rel: str) -> Path:
    root = workspace_root()
    if root is None:
        raise ToolError("No workspace folder is set (Settings → Agent).")
    rel = (rel or ".").strip().strip('"').strip("'")
    cand = Path(rel)
    full = cand if cand.is_absolute() else root / cand
    if not settings.get("agent.followSymlinks"):
        # block symlinks anywhere along the path
        cur = root
        for part in full.relative_to(root).parts if full.is_relative_to(root) else ():
            cur = cur / part
            if cur.is_symlink():
                raise ToolError(f"'{rel}' passes through a symlink, which is blocked.")
    resolved = full.resolve()
    if not resolved.is_relative_to(root):
        raise ToolError(f"'{rel}' is outside the workspace folder. Access denied.")
    if any(_ignored(p) for p in resolved.relative_to(root).parts):
        raise ToolError(f"'{rel}' is in an ignored location.")
    return resolved


def _ext_ok(p: Path) -> bool:
    allowed = [e.lower() if e.startswith(".") else "." + e.lower() for e in settings.csv("agent.allowedExtensions")]
    return not allowed or p.suffix.lower() in allowed


def _rel(p: Path) -> str:
    return str(p.relative_to(workspace_root())) or "."


def _read_text(p: Path) -> str:
    if not p.is_file():
        raise ToolError(f"'{_rel(p)}' is not a file.")
    if not _ext_ok(p):
        raise ToolError(f"Extension '{p.suffix}' is not allowed (Settings → Agent).")
    if p.stat().st_size > float(settings.get("agent.maxFileSizeMB")) * 1024 * 1024:
        raise ToolError(f"'{_rel(p)}' is larger than the {settings.get('agent.maxFileSizeMB')} MB limit.")
    data = p.read_bytes()
    if b"\x00" in data[:4096]:
        raise ToolError(f"'{_rel(p)}' looks like a binary file.")
    return data.decode("utf-8", "replace")


def describe(tool: str, args: dict) -> str:
    """Short human sentence for the UI / confirmation card."""
    a = args or {}
    return {
        "list_dir": f"Listing {a.get('path', '.')}",
        "read_file": f"Reading {a.get('path', '?')}",
        "search_files": f"Searching names for {a.get('pattern', '?')}",
        "grep": f"Searching text for “{a.get('text', '?')}”",
        "write_file": f"{'Appending to' if a.get('append') else 'Writing'} {a.get('path', '?')} ({len(str(a.get('content', '')))} chars)",
        "make_dir": f"Creating folder {a.get('path', '?')}",
        "delete_path": f"DELETING {a.get('path', '?')}",
    }.get(tool, tool)


def execute(tool: str, args: dict) -> dict:
    try:
        if tool not in enabled_tools():
            raise ToolError(f"Tool '{tool}' is not available (disabled in Settings → Agent).")
        fn = globals()[f"_t_{tool}"]
        result = fn(**(args or {}))
        log.info("tool %s ok", tool)
        return {"ok": True, "result": result}
    except ToolError as e:
        log.warning("tool %s refused: %s", tool, e)
        return {"ok": False, "error": str(e)}
    except TypeError as e:
        log.warning("tool %s bad arguments: %s", tool, e)
        return {"ok": False, "error": f"Bad arguments for {tool}: {e}"}
    except Exception as e:
        log.exception("tool %s crashed", tool)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _t_list_dir(path: str = ".") -> str:
    p = _safe(path)
    if not p.is_dir():
        raise ToolError(f"'{path}' is not a folder.")
    limit = int(settings.get("agent.maxListEntries"))
    entries = [e for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())) if not _ignored(e.name)]
    lines = [f"{e.name}/" if e.is_dir() else f"{e.name} ({e.stat().st_size} bytes)" for e in entries[:limit]]
    more = f"\n… and {len(entries) - limit} more" if len(entries) > limit else ""
    return "\n".join(lines) + more if lines else "(empty folder)"


def _t_read_file(path: str) -> str:
    p = _safe(path)
    text = _read_text(p)
    cap = int(settings.get("agent.maxReadChars"))
    return text[:cap] + (f"\n…[truncated, {len(text) - cap} more characters]" if len(text) > cap else "")


def _t_search_files(pattern: str) -> str:
    root = workspace_root()
    cap = int(settings.get("agent.maxSearchResults"))
    hits: list[str] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not _ignored(d)]
        for fn in fns:
            if _ignored(fn):
                continue
            if fnmatch.fnmatch(fn.lower(), pattern.lower()) or pattern.lower() in fn.lower():
                hits.append(str((Path(dp) / fn).relative_to(root)))
                if len(hits) >= cap:
                    return "\n".join(hits) + "\n…[result limit reached]"
    return "\n".join(hits) if hits else "No files matched."


def _walk_files(base: Path):
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if not _ignored(d)]
        for fn in fns:
            if not _ignored(fn):
                yield Path(dp) / fn


def _t_grep(text: str, path: str = ".") -> str:
    base = _safe(path)
    root = workspace_root()
    cap = int(settings.get("agent.maxSearchResults"))
    needle = text.lower()
    hits: list[str] = []
    files = [base] if base.is_file() else _walk_files(base)
    for f in files:
        try:
            if not _ext_ok(f) or f.stat().st_size > float(settings.get("agent.maxFileSizeMB")) * 1048576:
                continue
            for n, line in enumerate(f.read_text("utf-8", "ignore").splitlines(), 1):
                if needle in line.lower():
                    hits.append(f"{f.relative_to(root)}:{n}: {line.strip()[:160]}")
                    if len(hits) >= cap:
                        return "\n".join(hits) + "\n…[result limit reached]"
        except OSError:
            continue
    return "\n".join(hits) if hits else "No matches."


def _t_write_file(path: str, content: str, append: bool = False) -> str:
    p = _safe(path)
    if not _ext_ok(p):
        raise ToolError(f"Extension '{p.suffix}' is not allowed (Settings → Agent).")
    if p.exists() and p.is_dir():
        raise ToolError(f"'{path}' is a folder.")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if append else "w", encoding="utf-8") as fh:
        fh.write(str(content))
    return f"{'Appended' if append else 'Wrote'} {len(str(content))} characters to {_rel(p)}"


def _t_make_dir(path: str) -> str:
    p = _safe(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Folder ready: {_rel(p)}"


def _t_delete_path(path: str) -> str:
    p = _safe(path)
    if p == workspace_root():
        raise ToolError("Refusing to delete the workspace folder itself.")
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    else:
        raise ToolError(f"'{path}' does not exist.")
    return f"Deleted {path}"
