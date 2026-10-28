# Skill: memory & history

**Source:** `backend/skills/memory_history.py`
**Knowledge doc:** `knowledge/skills/memory_history.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `history_list_sessions` | `history_list_sessions(limit=20)   # list recent chat sessions` | misc | Listing up to 20 chat sessions |
| `history_read_session` | `history_read_session(session_id, limit=50)   # read one session's messages` | misc | Reading session {session_id} |
| `history_latest_session` | `history_latest_session()   # id of the most recent session` | misc | Finding the latest chat session |
| `history_prune` | `history_prune(days=30)   # delete sessions older than N days` | misc | Pruning sessions older than 30 days |
| `history_delete_session` | `history_delete_session(session_id, confirm='no')   # permanently delete one session` | misc | DELETING session {session_id} |

## What it does

Reads the SQLite chat history the backend already keeps (`backend/history.py`). No workspace
folder is needed — the history DB lives in the app data folder.

- `history_list_sessions(limit)` — lists recent sessions with id, title, and updated time
- `history_read_session(session_id, limit)` — reads one session's messages (role, time, model, truncated text)
- `history_latest_session()` — returns the id of the most recent session
- `history_prune(days)` — deletes sessions older than N days
- `history_delete_session(session_id, confirm)` — permanently deletes one session; refuses unless `confirm='yes'`

## Permission

`misc` — harmless reads; destructive calls (prune, delete) require `confirm='yes'` and raise
`ToolError` otherwise.

## Implementation

Uses `history.init_db()`, `history.get_sessions()`, `history.get_session_messages()`,
`history.prune()`, `history.delete_session()`, and `history.latest_session_id()` from
`backend/history.py`. The DB path comes from `CRYSTAL_DATA_DIR` env var or `./data`.
