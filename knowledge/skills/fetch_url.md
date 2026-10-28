# Skill: fetch_url

**Source:** `backend/skills/fetch_url.py`
**Knowledge doc:** `knowledge/skills/fetch_url.md`

## Tools registered

| Tool | Signature | Perm | Description |
|------|-----------|------|-------------|
| `fetch_url` | `fetch_url(url)   # read a web page as text` | net | Fetching {url} |

## What it does

Fetches a web page and returns it as plain text (scripts/styles and HTML stripped).

- Only `http://` and `https://` URLs allowed
- Redirects are not followed automatically (3xx → error with the redirect location)
- Loopback, private-network, link-local, reserved, and multicast addresses are blocked
- 1 MB response cap, 15 second timeout
- Output is truncated at `agent.maxReadChars`

## Permission

`net` — needs "Allow network access" enabled in Settings → Agent, and asks Allow/Deny
confirmation by default (`agent.confirmNet`).

## Security

Designed to prevent SSRF (server-side request forgery): the agent cannot be used to poke
your LAN or this app's own backend. Web pages may contain prompt-injection text, which is
why confirmation defaults on.

## Implementation

Uses `httpx.get()` with a `CrystalAgent/0.1` User-Agent, socket DNS resolution to check the
resolved IP, and `re` to strip HTML. `settings.get("agent.maxReadChars")` sets the truncation
cap.
