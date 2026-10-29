"""
Skill trust: decide whether a skill file in backend/skills/ is allowed to load.

Two kinds of skill file live in that folder:
  * code skills         *.py            run as Python inside the backend with the user's FULL privileges
  * instruction skills  *.md  or  <name>/SKILL.md   plain-text playbooks the model reads via use_skill(name)

Every file is hashed (SHA-256 of its bytes, line endings normalised so Windows/git checkouts agree).
A file may load only if its (relative path, hash) pair is either
  * in the bundled manifest  backend/skills_manifest.json  (skills shipped with Crystal), or
  * in the user's own list   setting `agent.trustedSkills`  (JSON {"file": "sha256"}, written by
    Settings -> Tools & diagnostics -> "Trust this skill").
Anything else is "unknown" (never seen) or "modified" (seen before, bytes changed) and is BLOCKED unless the user
switched `agent.skillTrust` to "warn". Changing one byte of a trusted file revokes its trust.
"""
import hashlib
import json
import logging
from pathlib import Path

from config import settings

log = logging.getLogger("backend.skill_trust")

MANIFEST = Path(__file__).resolve().parent / "skills_manifest.json"
TRUSTED = ("builtin", "trusted")


def digest(data: bytes) -> str:
    """SHA-256 of the file bytes with CRLF folded to LF (so a Windows checkout hashes the same)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _as_map(raw) -> dict[str, str]:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    return {str(k): str(v).strip().lower() for k, v in d.items() if isinstance(v, str)}


def builtin() -> dict[str, str]:
    try:
        return _as_map(json.loads(MANIFEST.read_text(encoding="utf-8")).get("files", {}))
    except Exception:
        log.warning("Bundled skill manifest %s is missing or unreadable; no skill counts as bundled", MANIFEST)
        return {}


def trusted() -> dict[str, str]:
    return _as_map(settings.get("agent.trustedSkills") or "{}")


def mode() -> str:
    """'require' (default): only trusted files load.  'warn': everything loads, untrusted files are flagged."""
    return "warn" if str(settings.get("agent.skillTrust")) == "warn" else "require"


def check(rel: str, sha: str) -> str:
    """'builtin' | 'trusted' | 'modified' (path known, bytes differ) | 'unknown'."""
    b, t = builtin(), trusted()
    if b.get(rel) == sha:
        return "builtin"
    if t.get(rel) == sha:
        return "trusted"
    return "modified" if (rel in b or rel in t) else "unknown"


def warning(kind: str, status: str) -> str:
    what = ("runs as Python with your full user privileges (it can read, change or delete anything you can)"
            if kind == "code" else "is text the model will follow as instructions")
    why = "has CHANGED since it was trusted" if status == "modified" else "has not been reviewed"
    return f"This skill file {why} and {what}. Read it before trusting it."


def discover(directory: Path) -> list[tuple[str, Path, str]]:
    """Skill files directly inside `directory` as (relative name, path, kind). Never descends further than
    <dir>/<name>/SKILL.md, skips '_*' and '.*', and skips anything whose real path is outside the folder (symlinks)."""
    out: list[tuple[str, Path, str]] = []
    root = directory.resolve()
    for p in sorted(directory.iterdir()):
        if p.name.startswith(("_", ".")):
            continue
        if p.is_dir():
            cand, rel, kind = p / "SKILL.md", f"{p.name}/SKILL.md", "instruction"
        elif p.suffix == ".py":
            cand, rel, kind = p, p.name, "code"
        elif p.suffix == ".md" and p.name.lower() != "readme.md":
            cand, rel, kind = p, p.name, "instruction"
        else:
            continue
        if not cand.is_file():
            continue
        if not cand.resolve().is_relative_to(root):
            log.warning("Ignoring %s: it resolves outside the skills folder", cand)
            continue
        out.append((rel, cand, kind))
    return out


def build_manifest(directory: Path) -> dict:
    files = {rel: digest(p.read_bytes()) for rel, p, _ in discover(directory)}
    return {"note": "SHA-256 of every skill shipped with Crystal. Regenerate with: python scripts/update_skill_manifest.py",
            "files": files}
