# Implementation Plan — Issue #6: Multi-workspace / project switching

**Branch:** `feature/multi-workspace-switching`
**Goal:** Let the user define several named workspace folders and switch the agent between them. Each workspace is a sandboxed folder the agent can read/write/delete/exec inside. Switching changes `agent.workspace` live (no restart needed for most tools), and each workspace can optionally carry its own permission switches.

---

## Current state (single workspace)

- `agent.workspace` (settings-schema.json, type `folder`) holds ONE folder path. `default = ""`.
- `tools.workspace_root()` resolves `agent.workspace` → a single `Path`.
- Every `read`/`write`/`delete`/`exec` tool calls `_safe(path)` which joins to the workspace, blocks symlinks/escape, rejects anything outside.
- `tools.enabled_tools()` hides `read`/`write`/`delete`/`exec` tools when no workspace is set.
- `server.py` `/api/test/workspace` reports the single workspace + enabled tools.
- Settings window (`renderer/settings.js`) renders `agent.workspace` as a `folder` field with Browse.
- `electron/settings-store.js` persists all settings as one flat JSON file in userData.

No concept of named/saved workspaces or switching between projects exists today.

---

## Design

### 1. Data model — named workspaces

Add a new setting `agent.workspaces` (type `text`, JSON) holding a list of workspace entries:

```json
[
  {"name": "notes", "path": "C:/Users/Priya/Notes", "permissions": {"read": true, "write": true, "delete": false, "exec": false}},
  {"name": "code",  "path": "D:/Projects/crystal", "permissions": {"read": true, "write": true, "delete": true, "exec": true}}
]
```

- `name` — unique slug, shown in the UI.
- `path` — absolute folder path (must exist).
- `permissions` — optional per-workspace overrides for read/write/delete/exec. If absent, falls back to the global `agent.allowRead/Write/Delete/Exec` switches.

Keep `agent.workspace` as the *active* workspace name (or path). Simplest: make `agent.workspace` hold the **name** of the active workspace, and derive the path from `agent.workspaces`. But `agent.workspace` is currently typed `folder` and used as a path by `workspace_root()`. To minimize breakage, I'll:

- Keep `agent.workspace` = active workspace **path** (as today) for backward compat with `workspace_root()`.
- Add `agent.workspaces` = the list (JSON).
- Add `agent.activeWorkspace` = name of the active workspace (for the switcher UI).

When the user switches workspaces, set `agent.workspace` to that workspace's path and `agent.activeWorkspace` to its name. Tools keep working unchanged because `workspace_root()` reads `agent.workspace`.

### 2. Settings schema additions

In `shared/settings-schema.json`, add to the **Agent** section:

| key | type | default | help |
|-----|------|---------|------|
| `agent.workspaces` | text | `"[]"` | List of named workspaces (JSON) |
| `agent.activeWorkspace` | text | `""` | Name of the currently active workspace |

And add a new **Workspaces** section (or a custom UI panel) for add/switch/delete. Since `renderer/settings.js` auto-renders schema fields, a JSON text field is unfriendly. I'll add a dedicated custom UI: a "Workspaces" tab/section in Settings → Agent that lists workspaces with a switch button, add/rename/delete, and path browse.

### 3. Backend changes (`backend/tools.py`, `backend/config.py`)

- `workspace_root()` — unchanged (reads `agent.workspace` path). Still the single source of truth for sandboxing.
- Add `workspaces()` → list of workspace dicts parsed from `agent.workspaces` (validated: name unique, path exists).
- Add `switch_workspace(name)` → sets `agent.workspace` = path, `agent.activeWorkspace` = name, returns the resolved path or raises `ToolError` if not found/invalid.
- `enabled_tools()` — when checking per-workspace permissions, prefer workspace-specific `permissions` over global `agent.allow*` switches. Keep it simple: if the active workspace has `permissions`, use those; else fall back to global switches.
- Add server endpoints:
  - `GET /api/workspaces` → list workspaces + active name.
  - `POST /api/workspaces/switch` → body `{name}` → switch active workspace.
  - `POST /api/workspaces` → add a workspace (name, path, permissions).
  - `DELETE /api/workspaces/{name}` → remove.
  - `POST /api/workspaces/{name}` → update path/permissions.

### 4. Settings UI changes (`renderer/settings.js`, `renderer/settings.html`)

- Add a **Workspaces** sub-tab inside Settings → Agent (or a new section). It shows:
  - Table: name, path, permissions (read/write/delete/exec toggles), active indicator.
  - "Switch" button per workspace (calls `/api/workspaces/switch`).
  - "Add workspace" form: name, path (Browse), permission toggles.
  - Rename / delete per workspace.
- Show active workspace name somewhere prominent (e.g., in the ball badge or settings header) so the user always knows which project is active.
- When switching, broadcast `settings:changed` so the backend applies the new `agent.workspace` live.

### 5. Electron / main

- No changes needed to `electron/main.js` for the core feature (settings are pushed live via `pushSettingsToBackend`).
- Optional: add IPC `workspaces:list` / `workspaces:switch` if the renderer needs direct access, but the existing `backend:api` generic handler already covers `/api/workspaces/*`.

### 6. Docs

- Update `docs/DOCUMENTATION.md`:
  - §9.x workspace sandbox → mention multiple workspaces + switching.
  - Settings reference table: add `agent.workspaces`, `agent.activeWorkspace`.
- Update `README.md` quick start if needed.

### 7. Tests (`tests/test_backend.py`)

- `test_workspaces_list_and_switch` — add two workspaces, switch, assert `agent.workspace` path changes and `enabled_tools()` reflects per-workspace perms.
- `test_workspace_permissions_override_global` — global allowWrite off, but workspace grants write → write_file works inside that workspace.
- `test_switch_to_invalid_workspace_errors` — switch to missing name → ToolError.
- `test_workspace_path_must_exist` — adding a workspace with a non-existent path → error.

---

## File changes

| File | Change |
|------|--------|
| `shared/settings-schema.json` | Add `agent.workspaces`, `agent.activeWorkspace` fields; optional new Workspaces section |
| `backend/tools.py` | `workspaces()`, `switch_workspace(name)`, per-workspace perm gating in `enabled_tools()`/`why_inactive()` |
| `backend/server.py` | `/api/workspaces` GET/POST/DELETE, `/api/workspaces/switch` POST |
| `backend/config.py` | none (schema path unchanged) |
| `renderer/settings.js` | Workspaces sub-tab UI (list, switch, add, rename, delete, active badge) |
| `renderer/settings.html` | container for Workspaces tab (if not already) |
| `tests/test_backend.py` | 4 new workspace tests |
| `docs/DOCUMENTATION.md` | workspace + settings reference updates |

---

## Order of work

1. Backend: data model + `switch_workspace` + `/api/workspaces` endpoints.
2. Settings UI: Workspaces tab + switcher + active badge.
3. Tests for all backend behavior.
4. Docs updates.
5. Manual verification: switch between two folders, confirm file tools only see the active one.

---

## Open questions (for your review)

1. Should `agent.workspace` keep holding the path (today's behavior), or switch to holding the workspace **name**? Keeping the path is less invasive; using the name is cleaner conceptually. I'd keep the path + add `agent.activeWorkspace` name.
2. Per-workspace permissions: scope to read/write/delete/exec only, or also `net`/skills? I'd scope to the four sandbox perms since those are workspace-bound.
3. Should deleting the active workspace auto-switch to another (or clear the workspace)? I'd clear `agent.workspace` and show "no workspace selected."
4. Where to persist `agent.workspaces` — inside `settings.json` (same file) or a separate `workspaces.json`? Same file is simpler (one settings store); separate file avoids mixing. I'll keep it in `settings.json` via the schema.

Review this plan, then tell me what to adjust before I start implementing.
