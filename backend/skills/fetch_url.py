"""
Fetch a web page as plain text. OFF by default: enable Settings → Agent → Allow network access.
Blocks localhost / private-network addresses (so a page or prompt cannot make the agent poke your LAN or
this app's own backend), http(s) only, 1 MB cap, 15 s timeout.
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from config import settings
from tools import ToolError


def _check_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ToolError(f"Could not resolve {host}.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolError("Local and private-network addresses are blocked.")


def fetch_url(url: str) -> str:
    u = urlparse(str(url))
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ToolError("Only http:// and https:// URLs are allowed.")
    _check_host(u.hostname)
    try:
        r = httpx.get(url, timeout=15, follow_redirects=False, headers={"User-Agent": "CrystalAgent/0.1"})
    except httpx.HTTPError as e:
        raise ToolError(f"Request failed: {e}")
    if 300 <= r.status_code < 400:
        raise ToolError(f"Redirected to {r.headers.get('location')}. Call fetch_url again with that address if you trust it.")
    if r.status_code >= 400:
        raise ToolError(f"HTTP {r.status_code}")
    text = r.content[:1_000_000].decode(r.encoding or "utf-8", "replace")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    cap = int(settings.get("agent.maxReadChars"))
    return text[:cap] + (f" …[truncated, {len(text) - cap} more characters]" if len(text) > cap else "")


def register(register_tool):
    register_tool(name="fetch_url", signature="fetch_url(url)   # read a web page as text", perm="net",
                  fn=fetch_url, describe=lambda a: f"Fetching {a.get('url', '?')}")
