"""
folder_profile: "what does this folder contain?" — a rich one-shot summary of a
workspace folder: item counts, total size, extension breakdown, newest and
largest files. Read-only, no writes, no confirm needed.

Knowledge doc: ../knowledge/skills/folder_profile.md
"""
import os
from collections import Counter
from pathlib import Path

from tools import ToolError, _safe, _ignored, _ext_ok, _rel


def _sizeof(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024
    return f"{num:.1f} PB"


def folder_profile(path: str = ".") -> str:
    """Summarize what a folder contains.

    Args:
        path: folder relative to the workspace (default "." = workspace root).
    """
    root = Path(_safe(path))
    if not root.is_dir():
        raise ToolError(f"'{path}' is not a folder.")

    file_count = 0
    dir_count = 0
    total_size = 0
    ext_counter: Counter[str] = Counter()
    files: list[tuple[int, Path]] = []   # (size, path) for largest-files ranking
    newest: list[tuple[float, Path]] = []  # (mtime, path)

    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not _ignored(d)]
        dir_count += len(dns)
        for fn in fns:
            if _ignored(fn):
                continue
            p = Path(dp) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            file_count += 1
            total_size += st.st_size
            ext_counter[p.suffix.lower() or "(no extension)"] += 1
            files.append((st.st_size, p))
            newest.append((st.st_mtime, p))

    files.sort(key=lambda t: t[0], reverse=True)
    newest.sort(key=lambda t: t[0], reverse=True)

    lines = [f"Folder profile: {_rel(root)}"]
    lines.append(f"  items: {file_count + dir_count} total  ({file_count} files, {dir_count} folders)")
    lines.append(f"  size: {_sizeof(total_size)}")

    if ext_counter:
        lines.append("  by extension:")
        for ext, cnt in ext_counter.most_common(6):
            lines.append(f"    {ext}: {cnt}")

    if files:
        lines.append("  largest files:")
        for size, p in files[:5]:
            lines.append(f"    {_sizeof(size)}  {_rel(p)}")

    if newest:
        from datetime import datetime
        lines.append("  newest files:")
        for mtime, p in newest[:5]:
            lines.append(f"    {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')}  {_rel(p)}")

    return "\n".join(lines)


def register(register_tool):
    register_tool(
        name="folder_profile",
        signature='folder_profile(path=".")   # summarize what a folder contains (counts, size, types, largest/newest)',
        perm="read", fn=folder_profile,
        describe=lambda a: f"Profiling folder {a.get('path', '.')}",
    )
