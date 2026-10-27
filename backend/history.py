"""SQLite chat history. (Rewritten: the old delete_session used a column that does not exist.)"""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("backend.history")
_DB: Path = Path("chat_history.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn():
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db(data_dir: Path) -> None:
    global _DB
    data_dir.mkdir(parents=True, exist_ok=True)
    _DB = data_dir / "chat_history.db"
    with _conn() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT, content TEXT, model TEXT, created_at TEXT)""")
        # migrate old DBs that lack the model column
        cols = [r["name"] for r in c.execute("PRAGMA table_info(messages)")]
        if "model" not in cols:
            c.execute("ALTER TABLE messages ADD COLUMN model TEXT")
    log.info("History database: %s", _DB)


def save_message(session_id: str, role: str, content: str, model: str | None = None) -> None:
    if not content or not content.strip():
        return
    now = _now()
    with _conn() as c:
        row = c.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row:
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        else:
            title = content.strip().splitlines()[0][:45]
            c.execute("INSERT INTO sessions VALUES (?,?,?,?)", (session_id, title, now, now))
        c.execute("INSERT INTO messages (session_id, role, content, model, created_at) VALUES (?,?,?,?,?)",
                  (session_id, role, content, model, now))


def get_sessions(limit: int = 50) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,))]


def get_session_messages(session_id: str, limit: int | None = None) -> list[dict]:
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT role, content, model, created_at FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,))]
    return rows[-limit:] if limit else rows


def latest_session_id() -> str | None:
    with _conn() as c:
        r = c.execute("SELECT id FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
        return r["id"] if r else None


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def prune(days: int) -> int:
    if days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM sessions WHERE updated_at < ?", (cutoff,))]
        for i in ids:
            c.execute("DELETE FROM messages WHERE session_id=?", (i,))
            c.execute("DELETE FROM sessions WHERE id=?", (i,))
    if ids:
        log.info("Pruned %d old sessions", len(ids))
    return len(ids)
