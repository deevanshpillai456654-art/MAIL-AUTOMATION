#!/usr/bin/env python3
"""Copy local-service/ into packaged dist/ and build/ service trees (run from repo root)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "backend"
DESTS = [
    ROOT / "dist" / "AIEmailOrganizer" / "service",
    ROOT / "build" / "output" / "windows" / "x64" / "AIEmailOrganizer" / "service",
]


def ignored(dirpath: str, names: list[str]) -> list[str]:
    skip = {"__pycache__", ".pytest_cache", ".mypy_cache"}
    out: list[str] = []
    for n in names:
        if n in skip:
            out.append(n)
        elif n.endswith(".pyc"):
            out.append(n)
    return out


def iter_files(top: Path) -> Iterable[Path]:
    if not top.is_dir():
        return
    for p in top.rglob("*"):
        if p.is_file():
            rel = p.relative_to(top)
            if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts:
                continue
            if p.suffix == ".pyc":
                continue
            yield p


def main() -> int:
    log_path = ROOT / "scripts" / "sync_packaged_service.log"
    lines: list[str] = []

    if not SRC.is_dir():
        msg = f"Missing source: {SRC}"
        print(msg, file=sys.stderr)
        log_path.write_text(msg + "\n", encoding="utf-8")
        return 1

    total_copied = 0
    for dest in DESTS:
        if not dest.parent.is_dir():
            lines.append(f"skip (parent missing): {dest}")
            continue
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SRC, dest, dirs_exist_ok=True, ignore=ignored)
        n = sum(1 for _ in iter_files(dest))
        total_copied = max(total_copied, n)
        lines.append(f"OK copytree -> {dest} (~{n} files under tree)")
        print(f"synced -> {dest}")

    lines.append(f"source_root={SRC}")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

