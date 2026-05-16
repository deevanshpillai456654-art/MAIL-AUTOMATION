from __future__ import annotations
import json, zipfile, shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
REQUIRED_PATCH_ENTRIES = {"manifest.json"}

def validate_patch_zip(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists(): return {"ok": False, "error":"patch file not found"}
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            names = set(zf.namelist())
            manifest = {}
            if "manifest.json" in names:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        return {"ok": bad is None and REQUIRED_PATCH_ENTRIES.issubset(names), "bad_file": bad, "entries": len(names), "manifest": manifest, "required": sorted(REQUIRED_PATCH_ENTRIES)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def update_status() -> Dict[str, Any]:
    return {"current_version":"9.7.0", "updates": [], "rollback_available": True, "preserves": ["accounts", "credentials", "rules", "automations", "templates", "reports", "integrations"]}
