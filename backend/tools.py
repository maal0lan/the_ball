"""
Sandboxed file tools for the agent. EVERY path is resolved and must stay inside
the workspace folder chosen in Settings. Returns plain dicts; never raises to the caller.
"""
import fnmatch
import importlib.util
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Callable

from config import settings

log = logging.getLogger("backend.tools")

# ---------------------------------------------------------------- registry
# Every tool (built-in or plugin skill) is one entry here. `perm` decides which setting
# gates it and whether it needs a confirmation click:
#   read / write / delete / exec  -> need a workspace folder (commands run inside it)
#   net                           -> network access, off by default
#   misc                          -> harmless, no workspace needed (e.g. get_time)
PERM_SETTING = {"read": "agent.allowRead", "write": "agent.allowWrite", "delete": "agent.allowDelete",
                "exec": "agent.allowExec", "net": "agent.allowNet", "misc": None}
NEEDS_WORKSPACE = {"read", "write", "delete", "exec"}
REGISTRY: dict[str, dict] = {}
SKILL_ERRORS: dict[str, str] = {}


class ToolError(Exception):
    """A tool refused or failed in a way the model/user should be told about."""


def register(name: str, signature: str, perm: str, fn: Callable, describe: Callable[[dict], str] | None = None,
             source: str = "builtin", confirm: bool = False) -> None:
    if perm not in PERM_SETTING:
        raise ValueError(f"unknown permission '{perm}' (use one of {sorted(PERM_SETTING)})")
    REGISTRY[name] = {"name": name, "sig": signature, "perm": perm, "fn": fn, "describe": describe, "source": source, "confirm": confirm}


def signature(name: str) -> str:
    return REGISTRY[name]["sig"]


def workspace_root() -> Path | None:
    w = str(settings.get("agent.workspace") or "").strip()
    if not w:
        return None
    p = Path(w).expanduser()
    return p.resolve() if p.is_dir() else None


def enabled_tools() -> list[str]:
    if not settings.get("agent.enabled"):
        return []
    has_ws = workspace_root() is not None
    off = settings.csv("agent.skillsDisabled")
    out = []
    for name, t in REGISTRY.items():
        if t["source"] != "builtin" and (not settings.get("agent.skillsEnabled") or name in off):
            continue
        if t["perm"] in NEEDS_WORKSPACE and not has_ws:
            continue
        key = PERM_SETTING[t["perm"]]
        if key and not settings.get(key):
            continue
        out.append(name)
    return out


def why_inactive(name: str) -> str:
    """Plain-English reason a tool is not available right now ('' if it is active)."""
    t = REGISTRY[name]
    if not settings.get("agent.enabled"):
        return "'Enable file tools' is OFF (Settings → Agent)"
    if t["source"] != "builtin":
        if not settings.get("agent.skillsEnabled"):
            return "'Load plugin skills' is OFF"
        if name in settings.csv("agent.skillsDisabled"):
            return "listed in 'Disabled skills'"
    if t["perm"] in NEEDS_WORKSPACE and workspace_root() is None:
        w = str(settings.get("agent.workspace") or "").strip()
        return (f"workspace folder '{w}' does not exist" if w else "NO WORKSPACE FOLDER is set (Settings → Agent → Workspace folder → Browse…)")
    key = PERM_SETTING[t["perm"]]
    if key and not settings.get(key):
        label = {"agent.allowRead": "Allow reading", "agent.allowWrite": "Allow writing", "agent.allowDelete": "Allow deleting",
                 "agent.allowExec": "Allow running commands", "agent.allowNet": "Allow network access"}[key]
        return f"'{label}' is OFF (Settings → Agent)"
    return ""


def needs_confirmation(tool: str) -> bool:
    t = REGISTRY.get(tool)
    if not t:
        return True
    if t.get("confirm"):
        return True
    return bool({"write": settings.get("agent.confirmWrites"), "delete": settings.get("agent.confirmWrites"),
                 "exec": settings.get("agent.confirmExec"), "net": settings.get("agent.confirmNet")}.get(t["perm"], False))


def list_skills() -> list[dict]:
    on = set(enabled_tools())
    return [{"name": n, "perm": t["perm"], "source": t["source"], "signature": t["sig"], "active": n in on,
             "reason": "" if n in on else why_inactive(n), "confirm": needs_confirmation(n)}
            for n, t in REGISTRY.items()] + [{"name": k, "error": v} for k, v in SKILL_ERRORS.items()]


# ---------------------------------------------------------------- plugin skills
def skills_dir() -> Path:
    return Path(os.getenv("CRYSTAL_SKILLS_DIR") or Path(__file__).resolve().parent / "skills")


def load_skills(directory: Path | None = None) -> int:
    """(Re)load every skills/*.py. A file may define  register(register_tool)  — see skills/_template.py."""
    for n in [n for n, t in REGISTRY.items() if t["source"] != "builtin"]:
        del REGISTRY[n]
    SKILL_ERRORS.clear()
    d = directory or skills_dir()
    if not d.is_dir():
        return 0
    count = 0
    for f in sorted(d.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"crystal_skill_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            before = len(REGISTRY)
            mod.register(lambda **kw: register(source=f"skills/{f.name}", **kw))
            count += len(REGISTRY) - before
            log.info("Loaded skill file %s", f.name)
        except Exception as e:
            SKILL_ERRORS[f.name] = f"{type(e).__name__}: {e}"
            log.exception("Skill file %s failed to load", f.name)
    log.info("Skills loaded: %d tool(s) from %s", count, d)
    return count


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
    t = REGISTRY.get(tool)
    try:
        if t and t["describe"]:
            return t["describe"](args or {})
    except Exception:
        pass
    return f"{tool} {args}" if args else tool


def execute(tool: str, args: dict) -> dict:
    try:
        if tool not in enabled_tools():
            raise ToolError(f"Tool '{tool}' is not available. Tools you can use right now: {', '.join(enabled_tools()) or 'none'}.")
        result = REGISTRY[tool]["fn"](**(args or {}))
        log.info("tool %s ok", tool)
        return {"ok": True, "result": result if isinstance(result, str) else str(result)}
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


# ---------------------------------------------------------------- run_command
# Windows cmd built-ins have no .exe, so they must be run through cmd /c
_CMD_BUILTINS = {"dir", "type", "echo", "ver", "where"}
_SECRET_ENV = ("CRYSTAL_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


def _exe_name(token: str) -> str:
    n = Path(token).name.lower()
    return n[:-4] if n.endswith(".exe") else n


def _t_run_command(command: str, cwd: str = ".") -> str:
    command = str(command).strip()
    if not command:
        raise ToolError("Empty command.")
    workdir = _safe(cwd)
    if not workdir.is_dir():
        raise ToolError(f"'{cwd}' is not a folder.")
    try:
        parts = shlex.split(command, posix=(os.name != "nt"))
    except ValueError as e:
        raise ToolError(f"Could not parse the command: {e}")
    if not parts:
        raise ToolError("Empty command.")
    exe = _exe_name(parts[0])
    if exe in {x.lower() for x in settings.csv("agent.execDenylist")}:
        raise ToolError(f"'{exe}' is on the deny list (Settings → Agent).")
    if settings.get("agent.execMode") == "allowlist" and exe not in {x.lower() for x in settings.csv("agent.execAllowlist")}:
        raise ToolError(f"'{exe}' is not on the allowed-commands list (Settings → Agent → Allowed commands).")
    # No shell is ever used, so  ;  &&  |  >  $(...)  have no special meaning and cannot chain extra commands.
    argv = ["cmd", "/c", *parts] if os.name == "nt" and exe in _CMD_BUILTINS else parts
    env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}   # never leak our tokens to child processes
    timeout = float(settings.get("agent.execTimeout"))
    cap = int(settings.get("agent.execMaxChars"))
    try:
        p = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except FileNotFoundError:
        raise ToolError(f"Command not found: {parts[0]}")
    except subprocess.TimeoutExpired as e:
        partial = ((e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
        raise ToolError(f"Command timed out after {timeout:g}s and was stopped. Output so far: {str(partial)[:cap]}")
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    text = f"exit code {p.returncode}"
    if out:
        text += f"\n[stdout]\n{out}"
    if err:
        text += f"\n[stderr]\n{err}"
    return text[:cap] + (f"\n…[output truncated at {cap} characters]" if len(text) > cap else "")


# ---------------------------------------------------------------- built-in registrations
_a = lambda a, k, d="?": a.get(k, d)
register("list_dir", 'list_dir(path=".")', "read", _t_list_dir, lambda a: f"Listing {_a(a, 'path', '.')}")
register("read_file", "read_file(path)", "read", _t_read_file, lambda a: f"Reading {_a(a, 'path')}")
register("search_files", "search_files(pattern)   # file-name glob such as *.md", "read", _t_search_files,
         lambda a: f"Searching names for {_a(a, 'pattern')}")
register("grep", 'grep(text, path=".")   # find text inside files', "read", _t_grep,
         lambda a: f"Searching text for “{_a(a, 'text')}”")
register("write_file", "write_file(path, content, append=false)", "write", _t_write_file,
         lambda a: f"{'Appending to' if a.get('append') else 'Writing'} {_a(a, 'path')} ({len(str(a.get('content', '')))} chars)")
register("make_dir", "make_dir(path)", "write", _t_make_dir, lambda a: f"Creating folder {_a(a, 'path')}")
register("delete_path", "delete_path(path)", "delete", _t_delete_path, lambda a: f"DELETING {_a(a, 'path')}")
register("run_command", 'run_command(command, cwd=".")   # runs one program with arguments, no pipes or &&',
         "exec", _t_run_command, lambda a: f"RUN COMMAND: {_a(a, 'command')}  (in {_a(a, 'cwd', '.')})")
