"""Replay payload compression with content hashes."""
from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import Any, Dict


def compress_replay_payload(payload: Dict[str, Any], level: int = 6) -> Dict[str, str | int]:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    compressed = zlib.compress(raw, max(1, min(9, level)))
    return {
        "encoding": "json+zlib+base64",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "compressed_bytes": len(compressed),
        "payload": base64.b64encode(compressed).decode("ascii"),
    }


def decompress_replay_payload(envelope: Dict[str, str | int]) -> Dict[str, Any]:
    if envelope.get("encoding") != "json+zlib+base64":
        raise ValueError("unsupported replay payload encoding")
    compressed = base64.b64decode(str(envelope["payload"]))
    raw = zlib.decompress(compressed)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != envelope.get("sha256"):
        raise ValueError("replay payload checksum mismatch")
    return json.loads(raw.decode("utf-8"))


__all__ = ["compress_replay_payload", "decompress_replay_payload"]
