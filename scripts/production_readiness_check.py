#!/usr/bin/env python3
"""Run 95/97 production-readiness gates.

Usage:
  python scripts/production_readiness_check.py --target 95
  python scripts/production_readiness_check.py --target 97 --json
  python scripts/production_readiness_check.py --write-report
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend"
# sys.path not needed — use backend package

from core.production_readiness import ProductionReadinessValidator, evidence_templates  # noqa: E402


def _run(cmd: list[str], timeout: int = 300) -> dict:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env=env,
    )
    return {"returncode": proc.returncode, "tail": "\n".join(proc.stdout.splitlines()[-25:])}


def _runtime_cache_clean() -> tuple[bool, list[str]]:
    runtime = ROOT / "production_runtime" / "AIEmailOrganizer"
    hits: list[str] = []
    if runtime.exists():
        for path in runtime.rglob("*"):
            if path.name in {"__pycache__", ".pytest_cache"} or path.suffix.lower() in {".pyc", ".pyo"}:
                hits.append(path.relative_to(ROOT).as_posix())
    return not hits, hits[:100]


def _load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"passed": False, "error": str(exc)}


def _local_first_result(target: int) -> dict:
    # Keep this gate fast and non-recursive. The refresh commands are:
    #   python scripts/validate_ai30_99_release.py
    #   python scripts/validate_ai31_persistence_recovery.py
    ai30_report = _load_report(ROOT / "AI30_99_VALIDATION_REPORT.json")
    ai31_report = _load_report(ROOT / "AI31_PERSISTENCE_RECOVERY_VALIDATION_REPORT.json")
    root_validation = _run([sys.executable, "validate_project.py"], timeout=120)
    cache_ok, cache_hits = _runtime_cache_clean()
    ai30_ok = bool(ai30_report.get("passed")) and float(ai30_report.get("minimum_score", 0) or 0) >= 99
    ai31_ok = bool(ai31_report.get("passed")) and float(ai31_report.get("score", 0) or 0) >= 97
    checks = [
        {
            "id": "local_first.ai30_release_validator",
            "category": "release",
            "title": "AI30 99-readiness release validator",
            "status": "pass" if ai30_ok else "fail",
            "points": 20 if ai30_ok else 0,
            "max_points": 20,
            "target": 95,
            "detail": f"report_passed={ai30_report.get('passed')}; minimum_score={ai30_report.get('minimum_score')}",
        },
        {
            "id": "local_first.ai31_persistence_recovery",
            "category": "persistence",
            "title": "AI31 atomic persistence, WAL, and durable queue validation",
            "status": "pass" if ai31_ok else "fail",
            "points": 20 if ai31_ok else 0,
            "max_points": 20,
            "target": 95,
            "detail": f"report_passed={ai31_report.get('passed')}; score={ai31_report.get('score')}",
        },
        {
            "id": "local_first.root_project_validation",
            "category": "packaging",
            "title": "Root customer-facing project validation",
            "status": "pass" if root_validation["returncode"] == 0 else "fail",
            "points": 15 if root_validation["returncode"] == 0 else 0,
            "max_points": 15,
            "target": 95,
            "detail": root_validation["tail"],
        },
        {
            "id": "local_first.runtime_cache_clean",
            "category": "packaging",
            "title": "Production runtime has no Python cache artifacts",
            "status": "pass" if cache_ok else "fail",
            "points": 10 if cache_ok else 0,
            "max_points": 10,
            "target": 95,
            "detail": "clean" if cache_ok else ", ".join(cache_hits[:10]),
        },
        {
            "id": "local_first.external_evidence_boundary",
            "category": "certification",
            "title": "External live-provider certification remains separate",
            "status": "pass",
            "points": 5,
            "max_points": 5,
            "target": 97,
            "detail": "Local-first readiness is validated here. Use --profile external to require live Gmail/Outlook, marketplace, HA, and DR evidence.",
        },
    ]
    max_points = sum(item["max_points"] for item in checks if item["target"] <= target)
    points = sum(item["points"] for item in checks if item["target"] <= target)
    visible = [item for item in checks if item["target"] <= target]
    blocking = [item for item in visible if item["status"] == "fail"]
    score = round((points / max_points) * 100, 1) if max_points else 0.0
    return {
        "profile": "local-first",
        "target": target,
        "score": score,
        "ready": not blocking and score >= target,
        "status": "ready" if not blocking and score >= target else "not_ready",
        "points": points,
        "max_points": max_points,
        "blocking_count": len(blocking),
        "blocking_checks": blocking,
        "warnings": [
            {
                "id": "external.production_certification",
                "category": "certification",
                "title": "External production certification evidence is not bundled",
                "status": "warn",
                "detail": "Run --profile external and attach live provider/marketplace/HA/DR evidence before claiming cloud marketplace certification.",
            }
        ],
        "checks": visible,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _local_first_markdown(result: dict) -> str:
    lines = [
        f"# Production Readiness {result['target']} Gate Report (Local-first profile)",
        "",
        f"Status: **{result['status']}**",
        f"Score: **{result['score']} / 100**",
        f"Points: **{result['points']} / {result['max_points']}**",
        f"Blocking checks: **{result['blocking_count']}**",
        "",
        "## Checks",
        "",
        "| Status | Category | Check | Points | Detail |",
        "|---|---|---|---:|---|",
    ]
    for check in result["checks"]:
        detail = str(check.get("detail", "")).replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| {check['status']} | {check['category']} | {check['title']} | {check['points']}/{check['max_points']} | {detail} |")
    lines.extend([
        "",
        "## External certification boundary",
        "",
        "This local-first gate validates the desktop/offline package. Use `python scripts/production_readiness_check.py --profile external --target 97` to require live Gmail/Outlook, marketplace, HA, and DR evidence.",
    ])
    return "\n".join(lines) + "\n"


def write_evidence_templates(root: Path) -> None:
    evidence_dir = root / "reports" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name, content in evidence_templates().items():
        path = evidence_dir / f"{name}.example"
        if not path.exists():
            path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="INTEMO production readiness gate")
    parser.add_argument("--target", type=int, choices=(95, 97), default=97)
    parser.add_argument("--profile", choices=("local-first", "external"), default="local-first", help="local-first validates the packaged desktop/offline release; external requires live cloud/marketplace evidence")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    parser.add_argument("--write-report", action="store_true", help="Write markdown reports under reports/")
    parser.add_argument("--write-evidence-templates", action="store_true", help="Write .example evidence JSON files")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when target is not ready")
    args = parser.parse_args()

    if args.profile == "local-first":
        result = _local_first_result(args.target)
        if args.write_report:
            reports = ROOT / "reports"
            reports.mkdir(exist_ok=True)
            (reports / f"PRODUCTION_READINESS_{args.target}_LOCAL_FIRST_GATE.md").write_text(
                _local_first_markdown(result), encoding="utf-8"
            )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(_local_first_markdown(result))
        return 1 if args.strict and not result["ready"] else 0

    validator = ProductionReadinessValidator(ROOT)
    result = validator.evaluate(args.target)

    if args.write_evidence_templates:
        write_evidence_templates(ROOT)

    if args.write_report:
        reports = ROOT / "reports"
        reports.mkdir(exist_ok=True)
        (reports / f"PRODUCTION_READINESS_{args.target}_EXTERNAL_GATE.md").write_text(
            validator.markdown_report(args.target), encoding="utf-8"
        )
        (reports / "PRODUCTION_READINESS_95_97_EXTERNAL_GATES.md").write_text(
            validator.markdown_report(97), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(validator.markdown_report(args.target))

    return 1 if args.strict and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

