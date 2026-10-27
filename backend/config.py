"""
Live settings for the backend.

Defaults come from shared/settings-schema.json (the same file the Electron
app and the settings window use), so there is exactly ONE place where a
setting is defined. The Electron app pushes the user's values to
POST /api/settings whenever they change; everything reads them through
`settings.get("section.key")` at the moment it needs them, so changes apply live.
"""
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("backend.config")


def setup_logging(level: str = "DEBUG") -> None:
    """One log format for everything. Electron parses the [LEVEL] tag."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Quiet very chatty libraries unless we are in DEBUG
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("backend.crash").critical(
            "Uncaught exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = _excepthook


def _schema_path() -> Path:
    env = os.getenv("CRYSTAL_SCHEMA")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "shared" / "settings-schema.json"


class Settings:
    def __init__(self) -> None:
        self.defaults: dict = {}
        self.values: dict = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        p = _schema_path()
        try:
            schema = json.loads(p.read_text(encoding="utf-8"))
            for sec in schema["sections"]:
                for fld in sec["fields"]:
                    self.defaults[fld["key"]] = fld["default"]
            log.info("Loaded %d setting defaults from %s", len(self.defaults), p)
        except Exception:
            log.exception("Could not read settings schema at %s", p)
        self.values = dict(self.defaults)

    def get(self, key: str, fallback=None):
        return self.values.get(key, self.defaults.get(key, fallback))

    def update(self, patch: dict) -> list[str]:
        changed = []
        for k, v in patch.items():
            if self.values.get(k) != v:
                self.values[k] = v
                changed.append(k)
        return changed

    def csv(self, key: str) -> list[str]:
        return [x.strip() for x in str(self.get(key, "") or "").split(",") if x.strip()]


settings = Settings()
