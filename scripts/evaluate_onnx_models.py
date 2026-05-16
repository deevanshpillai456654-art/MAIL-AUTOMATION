#!/usr/bin/env python3
"""Evaluate local ONNX classifiers before production activation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai.onnx_control_plane import DEFAULT_EVALUATION_CASES, OnnxAIControlPlane


def load_cases(path: Path | None) -> list[dict]:
    if path is None:
        return list(DEFAULT_EVALUATION_CASES)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("cases", [])
    if not isinstance(payload, list):
        raise ValueError("Evaluation dataset must be a list or an object with a cases list.")
    return [item for item in payload if isinstance(item, dict)]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate and optionally activate local ONNX models.")
    parser.add_argument("--model-dir", default=None, help="Model directory. Defaults to configured INTEMO model dir.")
    parser.add_argument("--model-name", default=None, help="Specific model name to evaluate. Defaults to all discovered models.")
    parser.add_argument("--dataset", type=Path, default=None, help="JSON list of evaluation cases.")
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument("--activate", action="store_true", help="Activate models only when evaluation passes.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plane = OnnxAIControlPlane(model_dir=args.model_dir)
    cases = load_cases(args.dataset)
    models = plane.discover_models()
    names = [args.model_name] if args.model_name else [item["name"] for item in models]

    if not names:
        result = {"status": "no_models", "evaluated": []}
        print(json.dumps(result, indent=2) if args.json else "No ONNX models found. Fallback classifier remains active.")
        return 0

    evaluated = [
        plane.evaluate_model(name, cases=cases, min_accuracy=args.min_accuracy, activate=args.activate)
        for name in names
    ]
    result = {"status": "complete", "evaluated": evaluated, "status_after": plane.status()}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in evaluated:
            print(
                f"{item.get('model')}: {item.get('status')} "
                f"accuracy={item.get('accuracy', 'n/a')} activated={item.get('activated', False)}"
            )
    return 0 if all(item.get("status") in {"accepted", "blocked"} for item in evaluated) else 1


if __name__ == "__main__":
    raise SystemExit(main())
