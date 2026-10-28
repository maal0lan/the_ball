"""Basic facts about this computer.

Knowledge doc: ../knowledge/skills/system_info.md
"""
import os
import platform
import shutil

from tools import workspace_root


def system_info() -> str:
    ws = workspace_root()
    lines = [f"OS: {platform.platform()}", f"CPU cores: {os.cpu_count()}", f"Python: {platform.python_version()}"]
    if ws:
        free = shutil.disk_usage(ws).free / 1e9
        lines.append(f"Free disk space at workspace: {free:.1f} GB")
    return "\n".join(lines)


def register(register_tool):
    register_tool(name="system_info", signature="system_info()   # OS, CPU cores, free disk space", perm="misc",
                  fn=system_info, describe=lambda a: "Checking system info")
