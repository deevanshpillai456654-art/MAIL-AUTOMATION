#!/usr/bin/env python3
"""Keep the per-browser extension folders aligned with the chrome canonical.

The 6 browser extension folders (chrome, edge, brave, firefox, opera, safari)
ship the same code with only per-browser manifest tweaks. This script copies
the shared files from ``extensions/chrome/`` to the other 5 folders so any
content fix lands everywhere at once.

Per-browser overrides that are NOT copied:
  * manifest.json        — each browser has its own description/gecko block
  * README.md            — per-browser narrative
  * integrity.json       — auto-generated from file hashes
  * icon*.png            — kept per-browser even if currently identical

Usage:
  python scripts/sync_browser_extensions.py            # apply sync
  python scripts/sync_browser_extensions.py --check    # exit 1 if drift
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "extensions" / "chrome"
TARGETS = [
    ROOT / "extensions" / "edge",
    ROOT / "extensions" / "brave",
    ROOT / "extensions" / "firefox",
    ROOT / "extensions" / "opera",
    ROOT / "extensions" / "safari",
]
SHARED_FILES = [
    "background.js",
    "content.js",
    "extension_runtime.js",
    "options.html",
    "options.js",
    "popup.html",
    "popup.js",
    "secure_message_bridge.js",
    "ui.css",
]


def _sha8(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:8]


def _find_drift() -> list[tuple[Path, str, str]]:
    """Return (target_path, canonical_sha, target_sha) for every drifted file."""
    drift: list[tuple[Path, str, str]] = []
    for target in TARGETS:
        for name in SHARED_FILES:
            src = CANONICAL / name
            dst = target / name
            if not src.exists() or not dst.exists():
                continue
            src_sha = _sha8(src)
            dst_sha = _sha8(dst)
            if src_sha != dst_sha:
                drift.append((dst, src_sha, dst_sha))
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit 1 if drift exists; do not modify files.")
    args = parser.parse_args(argv)

    drift = _find_drift()
    if args.check:
        if drift:
            print(f"Drift detected — {len(drift)} file(s) diverge from extensions/chrome/:")
            for dst, src_sha, dst_sha in drift:
                rel = dst.relative_to(ROOT)
                print(f"  {rel}  (canonical {src_sha}, target {dst_sha})")
            return 1
        print("OK: per-browser extension folders are in sync with extensions/chrome/.")
        return 0

    if not drift:
        print("Nothing to sync; per-browser extension folders already match extensions/chrome/.")
        return 0

    for dst, src_sha, dst_sha in drift:
        src = CANONICAL / dst.name
        shutil.copy2(src, dst)
        rel = dst.relative_to(ROOT)
        print(f"  synced {rel}  ({dst_sha} -> {src_sha})")
    print(f"Synced {len(drift)} file(s) from extensions/chrome/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
