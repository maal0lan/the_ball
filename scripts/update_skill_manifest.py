"""Regenerate backend/skills_manifest.json after you add or edit a bundled skill.

    python scripts/update_skill_manifest.py

Only run this for skill files you wrote or reviewed: it marks every file currently in backend/skills/ as bundled/trusted.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import skill_trust  # noqa: E402

manifest = skill_trust.build_manifest(ROOT / "backend" / "skills")
skill_trust.MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {skill_trust.MANIFEST} ({len(manifest['files'])} files)")
