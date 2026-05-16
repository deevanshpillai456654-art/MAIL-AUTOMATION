#!/usr/bin/env python3
"""Runtime debug probe for INTEMO v14.0.1B.

Starts the local backend on a temporary loopback port, exercises health, pages,
AI, semantic search, queues, workflows, and reports basic memory/runtime data.
No email content, OAuth tokens, or attachments are uploaded or transmitted.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import requests

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend"
PORT = int(os.environ.get("AIO_RUNTIME_DEBUG_PORT", "4571"))
BASE = f"http://127.0.0.1:{PORT}"
REPORT = ROOT / "reports" / "RUNTIME_DEBUG_PROBE_V9_1.json"
LOG = ROOT / "reports" / "runtime_debug_probe_v9_1.log"


def wait_for_service(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(BASE + "/api/v1/health", timeout=2).ok:
                return True
        except requests.RequestException:
            time.sleep(0.4)
    return False


def request(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        response = requests.request(method, BASE + path, timeout=8, **kwargs)
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        return {
            "path": path,
            "method": method,
            "status_code": response.status_code,
            "ok": response.ok,
            "latency_ms": elapsed,
            "body_preview": response.text[:250],
        }
    except Exception as exc:  # noqa: BLE001
        return {"path": path, "method": method, "ok": False, "error": repr(exc)}


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"API_PORT": str(PORT), "AIO_DISABLE_DATA_MIGRATION": "1", "LOG_LEVEL": "INFO"})
    with LOG.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=str(SERVICE),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )
        started = wait_for_service()
        results: List[Dict[str, Any]] = []
        memory_samples: List[Dict[str, Any]] = []
        try:
            if not started:
                raise RuntimeError("service_failed_to_start")

            get_paths = [
                "/",
                "/api/v1/health",
                "/dashboard",
                "/setup",
                "/admin",
                "/ai",
                "/api/v1/ai/runtime/status",
                "/api/v1/ai/diagnostics/status",
                "/api/v1/ai/cache/status",
                "/api/v1/ai/telemetry/status",
                "/api/v1/ai/vector-db/status",
                "/api/v1/ai/queue/status",
                "/api/v1/ai/command-center",
                "/api/v1/production/readiness-score",
                "/api/v1/production/guardrails",
                "/production-readiness",
            ]
            for path in get_paths:
                results.append(request("GET", path))

            payload = {
                "subject": "Urgent vendor payment approval",
                "sender": "Vendor Finance",
                "sender_email": "finance@example.com",
                "body": "Please approve invoice INV-901 today and schedule payment.",
                "text": "Urgent vendor payment approval for invoice INV-901 today.",
                "metadata": {"source": "runtime-debug-probe"},
            }
            posts = [
                ("/api/v1/ai/classify", payload),
                ("/api/v1/ai/extract", payload),
                ("/api/v1/ai/tags", payload),
                ("/api/v1/ai/priority", payload),
                ("/api/v1/ai/workflows/suggest", payload),
                ("/api/v1/ai/index/record", {"text": payload["text"], "namespace": "runtime-debug", "metadata": payload["metadata"]}),
                ("/api/v1/ai/search", {"query": "vendor invoice payment", "namespace": "runtime-debug", "top_k": 5}),
                ("/api/v1/ai/workflows/execute", {"name": "runtime-debug", "steps": [{"action": "classify_email", "payload": payload}]}),
            ]
            for path, body in posts:
                results.append(request("POST", path, json=body))

            # Light concurrency probe: repeated local-only AI classification should not deadlock or crash.
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(request, "POST", "/api/v1/ai/classify", json=payload) for _ in range(18)]
                for future in as_completed(futures):
                    results.append({"concurrent": True, **future.result()})

            try:
                import psutil

                p = psutil.Process(proc.pid)
                for _ in range(5):
                    if proc.poll() is not None:
                        break
                    info = p.memory_info()
                    memory_samples.append({
                        "rss_mb": round(info.rss / (1024 * 1024), 2),
                        "cpu_percent": p.cpu_percent(interval=0.2),
                        "threads": p.num_threads(),
                    })
            except Exception as exc:  # noqa: BLE001
                memory_samples.append({"error": repr(exc)})
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        log_text = LOG.read_text(encoding="utf-8", errors="ignore") if LOG.exists() else ""
        failures = [item for item in results if not item.get("ok")]
        report = {
            "version": "14.0.1B",
            "started": started,
            "exit_code": proc.returncode,
            "results": results,
            "failures": failures,
            "memory_samples": memory_samples,
            "log_file": str(LOG.relative_to(ROOT)),
            "log_errors_detected": [line for line in log_text.splitlines() if any(token in line.lower() for token in ("traceback", "exception", "error"))][:50],
            "summary": {
                "requests": len(results),
                "failed_requests": len(failures),
                "max_latency_ms": max((item.get("latency_ms", 0) for item in results), default=0),
                "max_rss_mb": max((item.get("rss_mb", 0) for item in memory_samples if isinstance(item.get("rss_mb"), (int, float))), default=0),
                "status": "pass" if started and not failures and proc.returncode in (0, -signal.SIGTERM, 143, None) else "fail",
            },
        }
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

