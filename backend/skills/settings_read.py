"""
Settings inspection (read-only): dump the agent's live settings so the model can answer
"what model am I using?", "is network access on?", "what workspace is set?" from a
conversation. Never writes — no permission switch needed, no workspace folder needed.

Knowledge doc: ../knowledge/skills/settings_read.md
"""
import json
import os
from pathlib import Path

from config import settings

_SCHEMA = Path(__file__).resolve().parent.parent.parent / "shared" / "settings-schema.json"


def _section_prefixes() -> dict[str, str]:
    """Map each schema section id to the key prefix of its fields (brain -> "llm.")."""
    try:
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for sec in schema.get("sections", []):
        sid = sec.get("id")
        keys = [str(f.get("key", "")) for f in sec.get("fields", []) if f.get("key")]
        if not sid or not keys:
            continue
        prefix = os.path.commonprefix(keys)
        dot = prefix.rfind(".")
        out[sid] = prefix[: dot + 1] if dot >= 0 else prefix
    return out


_PREFIXES = _section_prefixes()


def _section(section: str | None) -> dict:
    if section is None:
        return dict(settings.values)
    prefix = _PREFIXES.get(section)
    if prefix is None:
        return {}
    out = {}
    for k, v in settings.values.items():
        if k.startswith(prefix):
            out[k] = v
    return out


def settings_read(section: str = "") -> str:
    section = section or None
    data = _section(section)
    if not data:
        label = section or "all"
        return f"No settings found for section “{label}”."
    return "```\n" + json.dumps(data, indent=2) + "\n```"


def register(register_tool):
    register_tool(name="settings_read",
                  signature="settings_read(section='')   # read-only settings dump for a section (brain, voice, agent, …)",
                  perm="misc", fn=settings_read,
                  describe=lambda a: f"Reading settings section “{a.get('section', 'all')}”")
