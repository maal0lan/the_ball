# Implementation Plan --- Issue #6: Multi-Workspace / Project Switching

**Branch:** `feature/multi-workspace-switching`\
**Goal:** Allow users to create named workspace folders, assign
workspace-level permission restrictions, and switch the agent between
workspaces safely without restarting the application.

------------------------------------------------------------------------

## 1. Review of the original approach

The original plan has a sound low-impact direction:

-   Preserve `agent.workspace` as the active workspace path so existing
    sandbox code continues to work.
-   Add `agent.workspaces` to store named workspace definitions.
-   Add `agent.activeWorkspace` to identify the selected workspace in
    the UI.
-   Continue using `workspace_root()` as the source of truth for
    file-tool sandboxing.
-   Reuse the existing Electron backend API bridge rather than adding
    unnecessary IPC.

Keep this architecture, but make the security and consistency changes
below before implementation.

## 2. Required design decisions

### 2.1 Settings data model

Keep the existing setting as the active absolute path:

-   `agent.workspace`: active workspace path (existing setting;
    backward-compatible).
-   `agent.workspaces`: JSON-encoded list of saved workspace
    definitions.
-   `agent.activeWorkspace`: name of the active saved workspace.

Example:

``` json
{
  "agent.workspace": "D:/Projects/crystal",
  "agent.activeWorkspace": "crystal",
  "agent.workspaces": [
    {
      "name": "notes",
      "path": "C:/Users/Priya/Notes",
      "permissions": {
        "read": true,
        "write": true,
        "delete": false,
        "exec": false
      }
    },
    {
      "name": "crystal",
      "path": "D:/Projects/crystal",
      "permissions": {
        "read": true,
        "write": true,
        "delete": true,
        "exec": true
      }
    }
  ]
}
```

The example is illustrative. Follow the repository's existing settings
representation and naming conventions.

**Important:** `agent.workspace` remains the path consumed by existing
tools. Do not change it to a workspace name as part of this issue.

### 2.2 Permission precedence --- security-critical

Workspace permissions must never grant capabilities disabled globally.

Calculate each effective permission as:

``` python
effective_permission = global_permission and workspace_permission
```

If a workspace does not specify a permission, treat it as inheriting the
corresponding global setting:

``` python
workspace_permission = permissions.get(permission_name, True)
effective_permission = global_permission and workspace_permission
```

This means a workspace can restrict global permissions, but cannot
bypass a global deny.

Apply the same effective-permission calculation everywhere permissions
are enforced or reported, including:

-   `enabled_tools()`
-   `why_inactive()` (or the repository's equivalent)
-   Actual tool execution checks

Do not rely only on hiding a tool in the UI or tool list. Each operation
must enforce the effective permission at execution time.

Keep workspace-specific permissions limited to `read`, `write`,
`delete`, and `exec` for this issue. Network and skills permissions
remain global unless the existing architecture already requires
otherwise.

### 2.3 Switching must be a user-authorized operation

Every workspace switch requires an explicit confirmation in the UI.

The confirmation should identify both the destination workspace name and
its full path. If the user cancels, no settings or runtime state may
change.

Additional rules:

-   Do not automatically switch based on file contents, model output,
    tool output, or a detected project name.
-   Do not expose a model-callable operation that can switch workspaces
    without user confirmation.
-   Keep workspace-management endpoints within the application's
    existing trusted UI/API boundary and follow its existing
    authentication/authorization conventions.
-   The backend must validate the requested workspace even after the UI
    confirmation.

The confirmation is a UI authorization step; it must not be replaced by
a generic success toast or an implicit switch.

### 2.4 Consistent active-workspace state

Treat the active path and active name as one logical state change.

When switching:

1.  Find the saved workspace by its exact name.
2.  Validate and canonicalise its path.
3.  Resolve its effective permissions.
4.  Update `agent.workspace` and `agent.activeWorkspace` together
    through the settings store's safest available update mechanism.
5.  Notify the backend/runtime using the existing settings-change
    mechanism.
6.  Return the resulting active workspace information to the UI.

If validation or persistence fails, retain the previous active
workspace. Avoid partially updating one setting.

When a tool starts, it should resolve and retain the active workspace
root for that operation's duration. A workspace switch must not cause an
already-running operation to unexpectedly move to another root midway
through execution. Review long-running `exec` behaviour and any cached
workspace references.

### 2.5 Backward compatibility and restart behaviour

Existing installations may have only `agent.workspace` configured.

On startup:

-   Preserve the existing workspace path.
-   Do not clear or replace a valid legacy workspace.
-   If it is not represented in `agent.workspaces`, decide on a safe
    migration strategy: either create a clearly named legacy entry or
    continue treating it as the legacy active workspace until the user
    manages workspaces.
-   Do not silently select an arbitrary saved workspace if the active
    workspace is invalid.
-   Persist the selected workspace through the existing settings store
    so it remains active after restart.

If the active saved workspace no longer exists, show a clear
invalid/missing-workspace state and require the user to choose a valid
workspace. Do not silently switch to another folder.

### 2.6 Workspace path validation

Validate paths when adding or updating a workspace and again when
switching to it.

Requirements:

-   Path must be absolute.
-   Path must exist and be a directory.
-   Canonicalise/resolve the path before storing it.
-   Reject invalid paths and duplicate workspace names.
-   Define and enforce a consistent policy for duplicate canonical paths
    (prefer rejecting duplicates to avoid confusing aliases).
-   Preserve the existing `_safe(path)` traversal and symlink
    protections.
-   Do not weaken the existing sandbox boundary when introducing
    multiple workspaces.

Use the repository's existing cross-platform path conventions. Be
careful with Windows paths, case sensitivity, and path normalisation.

------------------------------------------------------------------------

## 3. Settings schema

File: `shared/settings-schema.json`

Add:

  -------------------------------------------------------------------------------
  Key                       Type              Default           Purpose
  ------------------------- ----------------- ----------------- -----------------
  `agent.workspaces`        `text` (or the    `"[]"`            Saved workspace
                            repository's                        definitions
                            suitable JSON                       
                            setting type)                       

  `agent.activeWorkspace`   `text`            `""`              Name of the
                                                                active saved
                                                                workspace
  -------------------------------------------------------------------------------

Keep `agent.workspace` unchanged.

Do not expose the raw JSON list as an ordinary editable text field if
the settings renderer automatically generates controls from the schema.
Use a dedicated Workspaces UI.

Check how schema defaults and existing settings migrations work before
changing the schema.

------------------------------------------------------------------------

## 4. Backend implementation

### 4.1 Workspace management helpers

Likely file: `backend/tools.py` (or a small dedicated workspace module
if that better matches the codebase).

Implement focused helpers:

-   `workspaces()` --- parse and validate the saved workspace list.
-   `get_active_workspace()` --- return the active workspace details.
-   `effective_workspace_permissions()` --- calculate global AND
    workspace permissions in one place.
-   `switch_workspace(name)` --- validate the destination and perform
    the atomic settings update.

Avoid duplicating permission precedence or path validation across
endpoints and tools.

Use the existing settings/configuration API rather than directly editing
settings JSON from multiple places.

### 4.2 Tool enforcement and result scoping

Keep `workspace_root()` as the active sandbox root.

Review every relevant file operation and confirm that it still resolves
paths relative to the active workspace:

-   read
-   write
-   delete
-   exec

Ensure:

-   Tool arguments cannot escape the active workspace.
-   Symlink protections continue to apply.
-   Effective permissions are checked when the operation executes.
-   Tool listings and inactive-reason messages reflect the same
    effective permissions.
-   Results from a tool invocation are produced from the workspace
    snapshot used by that invocation.

Do not assume that hiding a tool in `enabled_tools()` is sufficient
security enforcement.

### 4.3 API endpoints

Implement endpoints following the server's existing response and error
conventions:

  ---------------------------------------------------------------------------
  Method                  Endpoint                   Purpose
  ----------------------- -------------------------- ------------------------
  `GET`                   `/api/workspaces`          List saved workspaces
                                                     and active workspace

  `POST`                  `/api/workspaces`          Add a workspace

  `POST`                  `/api/workspaces/switch`   Switch to a saved
                                                     workspace

  `POST`                  `/api/workspaces/{name}`   Update workspace
                                                     name/path/permissions,
                                                     if supported

  `DELETE`                `/api/workspaces/{name}`   Remove a saved workspace
  ---------------------------------------------------------------------------

For every endpoint:

-   Validate input types and required fields.
-   Validate workspace names and paths server-side.
-   Return useful, consistent errors.
-   Do not return success until the settings update has succeeded.
-   Follow existing API authentication and trusted-renderer boundaries.

The switch endpoint must not itself be treated as proof that the user
confirmed the action. The trusted UI should show the confirmation before
issuing the request. Keep this endpoint inaccessible to model-driven or
untrusted callers.

### 4.4 Removing the active workspace

If the user removes the active saved workspace:

-   Clear `agent.workspace` and `agent.activeWorkspace` together.
-   Show a no-workspace-selected state.
-   Disable workspace-dependent tools.
-   Do not automatically activate another workspace.

If the user removes a non-active workspace, leave the current workspace
unchanged.

------------------------------------------------------------------------

## 5. Settings UI

Likely files:

-   `renderer/settings.js`
-   `renderer/settings.html`

Add a dedicated Workspaces section under Settings → Agent, following the
existing UI patterns.

### Workspace list

Display:

-   Workspace name
-   Folder path
-   Read/write/delete/exec permission indicators
-   Active workspace indicator
-   Switch, edit, and remove actions

### Add/edit workspace

Provide:

-   Workspace name
-   Folder path
-   Browse button using the existing folder picker
-   Read/write/delete/exec permission toggles

Validate obvious form errors in the UI, but always repeat validation in
the backend.

### Switch interaction

1.  User clicks Switch.
2.  Show a confirmation dialog containing the destination name and path.
3.  If cancelled, do nothing.
4.  If confirmed, call the switch endpoint.
5.  Update the active-workspace indicator only after the backend reports
    success.
6.  Refresh tool availability and any workspace-dependent UI.
7.  Display a useful error if switching fails.

Show the active workspace somewhere visible in the application (for
example, the settings header or existing workspace/status badge). Avoid
adding a second independent source of truth in renderer state.

Use the existing `settings:changed` / `pushSettingsToBackend` flow if it
correctly propagates the new settings. Verify this rather than assuming
a renderer-only update changes the backend runtime.

------------------------------------------------------------------------

## 6. Electron / main process

The original plan suggests no core changes are needed in
`electron/main.js`, which is reasonable if the existing generic
`backend:api` handler already supports these routes.

Before adding IPC:

-   Verify the generic API bridge can call the new endpoints.
-   Verify the renderer is allowed to call them under the existing
    security model.
-   Verify settings changes reach the backend without an application
    restart.

Do not add duplicate IPC handlers unless the existing bridge cannot
safely support the feature.

------------------------------------------------------------------------

## 7. Tests

Add tests in `tests/test_backend.py` or the repository's existing
relevant test modules.

### Core behaviour

1.  `test_workspaces_list_and_switch`
    -   Create two valid workspace entries.
    -   Switch between them.
    -   Assert active name and path are updated.
    -   Assert the active root changes.
2.  `test_workspace_permissions_restrict_global_permissions`
    -   Global permission enabled, workspace permission disabled.
    -   Assert the operation is denied.
3.  `test_workspace_permissions_cannot_override_global_deny`
    -   Global write disabled, workspace write enabled.
    -   Assert write remains denied.
4.  `test_workspace_permission_defaults_inherit_global`
    -   Omit a workspace permission.
    -   Assert the global setting determines the effective permission.
5.  `test_switch_to_invalid_workspace_errors`
    -   Attempt to switch to an unknown name.
    -   Assert an error is returned and the old active workspace remains
        unchanged.
6.  `test_workspace_path_must_exist`
    -   Attempt to add a missing path.
    -   Assert validation fails.
7.  `test_workspace_path_must_be_directory`
    -   Attempt to add a file path.
    -   Assert validation fails.
8.  `test_duplicate_workspace_name_rejected`
    -   Attempt to add a second workspace with the same name.
    -   Assert validation fails.
9.  `test_delete_active_workspace_clears_selection`
    -   Delete the active entry.
    -   Assert both active settings are cleared and workspace tools are
        unavailable.
10. `test_delete_inactive_workspace_preserves_active`
    -   Delete another entry.
    -   Assert the active path and name do not change.

### Isolation and compatibility

11. `test_file_tools_are_scoped_to_active_workspace`
    -   Create separate temporary directories.
    -   Switch between them and verify file operations cannot access the
        other workspace through relative or traversal paths.
12. `test_workspace_symlink_escape_blocked`
    -   Verify the existing symlink boundary remains effective.
13. `test_legacy_single_workspace_preserved`
    -   Start with only the old `agent.workspace` setting.
    -   Verify the path is not lost during initialisation or migration.
14. `test_active_workspace_persisted_after_restart`
    -   Save a selection, reload settings/backend state, and verify the
        same workspace remains active.
15. `test_failed_switch_does_not_partially_update_settings`
    -   Simulate validation or persistence failure.
    -   Verify both active settings retain their previous values.
16. `test_running_operation_keeps_workspace_snapshot`
    -   Where the architecture permits a deterministic test, verify a
        switch during a long-running operation does not redirect that
        operation to another workspace.

Also test the API response/error paths and UI confirmation/cancellation
behaviour using the project's existing test conventions.

------------------------------------------------------------------------

## 8. Documentation

Update `docs/DOCUMENTATION.md`:

-   Explain named workspaces and how to add/remove them.
-   Explain how to switch and that switching requires confirmation.
-   Explain the active workspace indicator.
-   Document the global/workspace permission rule: workspace settings
    can restrict global permissions, never override a global deny.
-   Update the settings reference for `agent.workspaces` and
    `agent.activeWorkspace`.
-   Explain legacy single-workspace compatibility if relevant to users.

Update `README.md` only if the existing quick-start or workspace
instructions would otherwise become inaccurate.

------------------------------------------------------------------------

## 9. Recommended implementation order

Work in small, verifiable steps rather than changing the backend and UI
simultaneously.

### Phase 1 --- Inspect existing architecture

Before editing, trace:

-   Settings schema and settings-store read/write/update behaviour.
-   `workspace_root()` and `_safe(path)`.
-   Every file tool and its permission check.
-   `enabled_tools()` and `why_inactive()`.
-   Settings-change propagation from Electron to backend.
-   Existing API route conventions and renderer
    folder-picker/confirmation patterns.

Record any assumptions that differ from this plan.

### Phase 2 --- Backend data model and validation

-   Add schema fields.
-   Implement parsing, validation, and canonical path handling.
-   Preserve legacy `agent.workspace`.
-   Add effective permission calculation.
-   Add atomic switch and removal behaviour.

Run focused backend tests before proceeding.

### Phase 3 --- Backend API

-   Add list/add/update/remove/switch endpoints.
-   Verify error handling and trusted caller boundaries.
-   Confirm that a successful switch updates the runtime without
    restarting the app.

### Phase 4 --- Security and isolation tests

-   Test permission combinations.
-   Test path traversal and symlink behaviour.
-   Test active/inactive deletion.
-   Test legacy settings and restart persistence.
-   Test operation workspace snapshots.

Do not proceed to UI polish until the backend security tests pass.

### Phase 5 --- Settings UI

-   Add the Workspaces section.
-   Implement add/edit/remove.
-   Add confirmation before switching.
-   Update the active indicator only after backend success.
-   Refresh tool availability after a switch.

### Phase 6 --- Manual verification

Use two separate temporary directories with recognisable files.

1.  Add both folders as named workspaces.
2.  Confirm the first workspace is active.
3.  Read a file from the first workspace.
4.  Switch to the second workspace and confirm the dialog identifies its
    name and path.
5.  Read a file from the second workspace.
6.  Attempt to access the first workspace from the second workspace and
    verify it is blocked.
7.  Cancel a switch and verify the active workspace does not change.
8.  Disable a global permission while enabling it in a workspace and
    verify the operation remains denied.
9.  Restart the application and verify the selected workspace is
    preserved.
10. Remove the active workspace and verify the app enters the
    no-workspace-selected state.

### Phase 7 --- Documentation and final checks

-   Update documentation.
-   Run the complete relevant test suite.
-   Review the final diff for unrelated changes.
-   Confirm no model-driven or automatic workspace switching path was
    introduced.

------------------------------------------------------------------------

## 10. Scope boundaries

Keep this issue focused.

**In scope:**

-   Named workspace definitions.
-   Add/edit/remove workspace settings.
-   User-confirmed switching.
-   Active workspace persistence.
-   Workspace-specific read/write/delete/exec restrictions.
-   Correct tool scoping and backward compatibility.

**Out of scope unless the existing architecture makes them necessary:**

-   Per-workspace network permissions.
-   Per-workspace skills or model configuration.
-   Automatic project detection or switching.
-   Multiple simultaneously active workspaces.
-   A new sandbox implementation.
-   Unrelated Electron IPC refactoring.

------------------------------------------------------------------------

## 11. Decisions to settle before implementation

1.  **Workspace names:** Use a simple, validated name format. Decide
    whether names are case-insensitive and enforce uniqueness
    consistently.
2.  **Duplicate paths:** Prefer rejecting two workspace entries that
    resolve to the same canonical directory.
3.  **Legacy workspace:** Preserve the old path. Decide whether to
    create a legacy named entry automatically or retain it as an unsaved
    active workspace until the user adds it.
4.  **Permission defaults:** Missing workspace permission values inherit
    the global setting; explicit `false` restricts the workspace.
5.  **Active workspace deletion:** Clear the active selection; do not
    auto-switch.
6.  **Switch confirmation:** Confirmation belongs in the trusted UI and
    must happen for every switch, including switching back to a
    previously used workspace.

## Final recommendation

Retain the original plan's compatibility-first architecture, but
implement permission intersection, atomic active-state updates, strict
path validation, and explicit user confirmation as non-negotiable
requirements.

The safest sequence is to finish and test the backend security model
first, then build the Settings UI on top of the verified API. This keeps
the feature manageable while protecting the existing one-workspace
sandbox behaviour.
