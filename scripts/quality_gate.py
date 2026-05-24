#!/usr/bin/env python
"""Single-command backend quality gate.

Runs the security/correctness tooling installed for this project against the
backend, in order of cost (fastest first), and stops on the first failure unless
--continue-on-failure is passed.

Tools:
  1. ruff      — lint (security S, bug-risk B, correctness E/F/W, imports I)
  2. bandit    — SAST (HIGH severity only by default)
  3. pip-audit — known-CVE scan of installed packages
  4. pytest    — backend test suite (excluding frontend/visual/extension tests)

Exit codes mirror standard CI conventions:
  0  all gates passed
  1  at least one gate failed
  2  usage error / tool missing

Skip individual gates with --skip ruff,bandit,pip-audit,pytest.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():  # POSIX fallback
    VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

# Tests excluded from backend gate (frontend / visual smoke / extension packaging)
EXCLUDED_TESTS = [
    "tests/test_frontend_production_polish.py",
    "tests/test_dashboard_visual_smoke.py",
    "tests/test_extension_packaging.py",
]


def _python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def _run(label: str, cmd: list[str], cwd: Path = ROOT) -> tuple[bool, float]:
    start = time.time()
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd)  # noqa: S603 — controlled internal arg list
    elapsed = time.time() - start
    ok = proc.returncode == 0
    print(f"--- {label}: {'PASS' if ok else 'FAIL'} ({elapsed:.1f}s, exit={proc.returncode})")
    return ok, elapsed


def gate_ruff() -> bool:
    return _run("ruff (lint)", [_python(), "-m", "ruff", "check", "backend"])[0]


def gate_bandit() -> bool:
    # -lll = HIGH severity only; matches the audit's "274 HIGH findings" framing.
    return _run(
        "bandit (HIGH only)",
        [_python(), "-m", "bandit", "-r", "backend", "-lll", "-q"],
    )[0]


def gate_pip_audit() -> bool:
    return _run("pip-audit (CVE scan)", [_python(), "-m", "pip_audit"])[0]


def gate_pytest() -> bool:
    cmd = [_python(), "-m", "pytest", "tests/", "-q", "--no-header", "--tb=line"]
    for excluded in EXCLUDED_TESTS:
        cmd.extend(["--ignore", excluded])
    return _run("pytest (backend)", cmd)[0]


GATES = {
    "ruff": gate_ruff,
    "bandit": gate_bandit,
    "pip-audit": gate_pip_audit,
    "pytest": gate_pytest,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated list of gates to skip (ruff,bandit,pip-audit,pytest).",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Run all gates regardless of earlier failures.",
    )
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        print("ERROR: project .venv not found at", VENV_PYTHON, file=sys.stderr)
        return 2

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    unknown = skip - set(GATES)
    if unknown:
        print(f"ERROR: unknown gate(s) in --skip: {','.join(sorted(unknown))}", file=sys.stderr)
        return 2

    total_start = time.time()
    results: list[tuple[str, bool]] = []
    overall_ok = True

    for name, fn in GATES.items():
        if name in skip:
            print(f"\n=== {name}: SKIPPED ===")
            continue
        try:
            ok = fn()
        except FileNotFoundError as exc:
            print(f"ERROR: tool not installed for gate {name!r}: {exc}", file=sys.stderr)
            ok = False
        results.append((name, ok))
        if not ok:
            overall_ok = False
            if not args.continue_on_failure:
                break

    total = time.time() - total_start
    print("\n=== Summary ===")
    for name, ok in results:
        print(f"  {name:<10}  {'PASS' if ok else 'FAIL'}")
    print(f"  total      {total:.1f}s")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
