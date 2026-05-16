"""Extension package integrity manifest generator."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict

@dataclass(frozen=True)
class IntegrityFinding:
    path: str
    reason: str

class ExtensionIntegrityEngine:
    def build_manifest(self, extension_dir: str | Path) -> Dict[str, str]:
        root = Path(extension_dir)
        hashes: Dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name not in {"integrity.json"}:
                hashes[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
        return hashes

    def verify_manifest(self, extension_dir: str | Path, manifest: Dict[str, str]) -> list[IntegrityFinding]:
        root = Path(extension_dir)
        findings: list[IntegrityFinding] = []
        for rel, expected in manifest.items():
            path = root / rel
            if not path.exists():
                findings.append(IntegrityFinding(rel, "missing_file"))
                continue
            actual = sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                findings.append(IntegrityFinding(rel, "hash_mismatch"))
        return findings
