#!/usr/bin/env python3
"""Create a clean release ZIP from the working tree.

Uses ``git ls-files --cached --others --exclude-standard`` so that everything
in .gitignore (.git metadata, build/, dist/, logs/, data/, *.db, .env,
node_modules/, etc.) is automatically excluded.

Usage:
    python scripts/create_release_zip.py
    python scripts/create_release_zip.py --output AI36_release.zip
    python scripts/create_release_zip.py --output AI36_release.zip --prefix AI36_curated/
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Runtime artifacts that must never appear in a release ZIP even if accidentally
# committed to git (e.g. tracked before .gitignore was in place).
_NEVER_PACKAGE: frozenset[str] = frozenset({
    ".env",
    ".env.local",
})
_NEVER_PACKAGE_SUFFIXES: frozenset[str] = frozenset({
    ".db", ".db-journal", ".db-wal", ".db-shm",
    ".log", ".pyc", ".pyo",
})
_NEVER_PACKAGE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "logs", "build", "dist",
})


def _is_excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in _NEVER_PACKAGE_DIRS for p in parts):
        return True
    if rel.name in _NEVER_PACKAGE:
        return True
    if rel.suffix.lower() in _NEVER_PACKAGE_SUFFIXES:
        return True
    return False


def _git_files() -> list[Path]:
    """Return all files that git would include (tracked + untracked-but-not-gitignored)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[Path] = []
    skipped: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rel = Path(line)
        if _is_excluded(rel):
            skipped.append(line)
            continue
        p = ROOT / rel
        if p.is_file():
            paths.append(p)
    if skipped:
        print(f"Excluded {len(skipped)} runtime artifact(s) from ZIP (tracked but not releasable):")
        for s in skipped[:20]:
            print(f"  {s}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")
    return paths


def _default_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return ROOT.parent / f"AI36_curated_{stamp}.zip"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a clean release ZIP")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output ZIP path (default: ../AI36_curated_<timestamp>.zip)",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Path prefix inside the ZIP (e.g. 'AI36_curated/')",
    )
    args = parser.parse_args()

    output: Path = args.output or _default_output()
    output = output.resolve()
    prefix: str = args.prefix.rstrip("/") + "/" if args.prefix else ""

    try:
        files = _git_files()
    except subprocess.CalledProcessError as exc:
        print(f"git ls-files failed: {exc.stderr}", file=sys.stderr)
        return 1

    if not files:
        print("No files found — is this a git repository?", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(files):
            arcname = prefix + p.relative_to(ROOT).as_posix()
            zf.write(p, arcname)
            total += 1

    size_mb = output.stat().st_size / 1_048_576
    print(f"Created: {output}")
    print(f"  {total} files, {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
