# Skill: system_info

**Source:** `backend/skills/system_info.py`
**Knowledge doc:** `knowledge/skills/system_info.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `system_info` | `system_info()   # OS, CPU cores, free disk space` | misc | Checking system info |

## What it does

Returns basic facts about the computer running the backend:
- OS platform
- CPU core count
- Python version
- Free disk space at the workspace folder (if one is set)

Example output:

```
OS: Windows-10-10.0.26300-SP0
CPU cores: 8
Python: 3.11.x
Free disk space at workspace: 123.4 GB
```

## Permission

`misc` — harmless, no workspace folder needed.

## Implementation

Uses `platform.platform()`, `os.cpu_count()`, `platform.python_version()`, and
`shutil.disk_usage()` on `tools.workspace_root()`.
