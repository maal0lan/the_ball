"""
Open apps, files, or URLs in the default browser. Also handles search-style
requests like "open this song on youtube" → opens a YouTube search results page.

This skill needs no workspace folder (it launches apps / opens URLs, not files
inside the workspace), but it *is* powerful — it can start any local program —
so it always asks for Allow/Deny first (confirm=True).
"""
import os
import shlex
import subprocess
import webbrowser
from urllib.parse import quote_plus

from tools import ToolError


def _youtube_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def _google_search_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


def open_app(target: str) -> str:
    """Open an app, file, or URL.

    Examples:
      - "notepad"          → launches Notepad
      - "https://youtube.com" → opens in default browser
      - "open this song on youtube" → YouTube search for "this song"
      - "search for weather" → Google search
    """
    target = str(target).strip()
    if not target:
        raise ToolError("Nothing to open — pass an app name, file path, or URL.")

    lower = target.lower()

    # --- YouTube search: "open/play <song> on youtube" ---
    if "youtube" in lower or " yt " in f" {lower} " or lower.endswith(" yt"):
        query = target
        for word in ("open", "play", "search", "on", "youtube", "yt", "this", "that", "song", "video", "for"):
            query = query.replace(word, " ")
        query = " ".join(query.split())
        url = _youtube_search_url(query) if query else "https://www.youtube.com"
        webbrowser.open(url)
        return f"Opened YouTube for “{query}”." if query else "Opened YouTube."

    # --- General web search: "search for X" / "google X" ---
    if lower.startswith(("search ", "google ")):
        query = target.split(" ", 1)[1] if " " in target else ""
        if not query:
            raise ToolError("Nothing to search for — tell me what to look up.")
        webbrowser.open(_google_search_url(query))
        return f"Searched Google for “{query}”."

    # --- Direct URL ---
    if target.startswith(("http://", "https://")):
        webbrowser.open(target)
        return f"Opened {target}."
    if target.startswith("www."):
        webbrowser.open("https://" + target)
        return f"Opened https://{target}."

    # --- Local app or file ---
    try:
        os.startfile(target)  # Windows: opens apps, files, folders, URLs
        return f"Opened {target}."
    except (OSError, FileNotFoundError):
        pass

    # --- Try as a command via subprocess ---
    try:
        parts = shlex.split(target)
        subprocess.Popen(parts)
        return f"Launched {target}."
    except (OSError, FileNotFoundError):
        pass

    raise ToolError(f"Could not open '{target}' — not a recognized app, file, or URL.")


def register(register_tool):
    register_tool(
        name="open_app",
        signature="open_app(target)   # open an app, file, or URL (e.g. 'notepad', 'youtube', 'open song on youtube')",
        perm="misc",
        fn=open_app,
        confirm=True,
        describe=lambda a: f"Opening {a.get('target', '?')}",
    )
