"""JSONL event archival with checksummed records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable


class EventArchiver:
    def __init__(self, archive_dir: str | Path):
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def archive(self, stream: str, events: Iterable[Dict]) -> Path:
        path = self.archive_dir / f"{stream}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                payload = json.dumps(event, sort_keys=True, default=str)
                digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                handle.write(json.dumps({"sha256": digest, "event": event}, sort_keys=True, default=str) + "\n")
        return path


__all__ = ["EventArchiver"]
