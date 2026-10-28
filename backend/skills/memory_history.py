"""
Memory & history: list chat sessions, read a session's messages, prune/delete sessions.

Reads the SQLite chat history the backend already keeps (backend/history.py). No workspace
folder is needed — the history DB lives in the app data folder. Destructive calls (prune,
delete) refuse unless you pass confirm='yes'.

Knowledge doc: ../knowledge/skills/memory_history.md
"""
import os
from pathlib import Path

import history
from tools import ToolError


def _ensure_db() -> None:
    if history._DB is None:
        history.init_db(Path(os.getenv("CRYSTAL_DATA_DIR", "data")))


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def history_list_sessions(limit: int = 20) -> str:
    _ensure_db()
    rows = history.get_sessions(limit=max(1, min(int(limit), 100)))
    if not rows:
        return "No chat sessions yet."
    lines = [f"{len(rows)} session(s):"]
    for r in rows:
        lines.append(f"• {r['id']} — “{_short(r['title'])}” — updated {r['updated_at']}")
    return "\n".join(lines)


def history_read_session(session_id: str, limit: int = 50) -> str:
    _ensure_db()
    msgs = history.get_session_messages(str(session_id), limit=max(1, min(int(limit), 200)))
    if not msgs:
        return f"No messages found for session {session_id}."
    lines = [f"Session {session_id} — {len(msgs)} message(s):"]
    for m in msgs:
        tag = f" ({m['model']})" if m.get("model") else ""
        lines.append(f"[{m['role']}{tag}] {m['created_at']}: {_short(m['content'], 200)}")
    return "\n".join(lines)


def history_latest_session() -> str:
    _ensure_db()
    sid = history.latest_session_id()
    return sid or "No chat sessions yet."


def history_prune(days: int = 30) -> str:
    _ensure_db()
    days = int(days)
    if days <= 0:
        return "Prune skipped: days must be >= 1."
    n = history.prune(days)
    return f"Pruned {n} session(s) older than {days} day(s)."


def history_delete_session(session_id: str, confirm: str = "no") -> str:
    if str(confirm).strip().lower() != "yes":
        raise ToolError("Refusing to delete a session — pass confirm='yes' to proceed.")
    _ensure_db()
    ids = {s["id"] for s in history.get_sessions()}
    sid = str(session_id)
    if sid not in ids:
        raise ToolError(f"Session {sid} not found.")
    before = len(ids)
    history.delete_session(sid)
    return f"Deleted session {sid} ({before} -> {len(history.get_sessions())} sessions)."


def register(register_tool):
    register_tool(name="history_list_sessions",
                  signature="history_list_sessions(limit=20)   # list recent chat sessions",
                  perm="misc", fn=history_list_sessions,
                  describe=lambda a: f"Listing up to {a.get('limit', 20)} chat sessions")
    register_tool(name="history_read_session",
                  signature="history_read_session(session_id, limit=50)   # read one session's messages",
                  perm="misc", fn=history_read_session,
                  describe=lambda a: f"Reading session {a.get('session_id', '?')}")
    register_tool(name="history_latest_session",
                  signature="history_latest_session()   # id of the most recent session",
                  perm="misc", fn=history_latest_session,
                  describe=lambda a: "Finding the latest chat session")
    register_tool(name="history_prune",
                  signature="history_prune(days=30)   # delete sessions older than N days",
                  perm="misc", fn=history_prune,
                  describe=lambda a: f"Pruning sessions older than {a.get('days', 30)} days")
    register_tool(name="history_delete_session",
                  signature="history_delete_session(session_id, confirm='no')   # permanently delete one session",
                  perm="misc", fn=history_delete_session,
                  describe=lambda a: f"DELETING session {a.get('session_id', '?')}")
