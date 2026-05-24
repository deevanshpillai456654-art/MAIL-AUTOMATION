"""
Metrics and analytics for AI Email Organizer
"""

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

_log = logging.getLogger(__name__)


class MetricsCollector:
    def __init__(self, storage_path: str = None):
        if storage_path is None:
            base_path = Path(__file__).parent.parent / "data"
            base_path.mkdir(parents=True, exist_ok=True)
            storage_path = str(base_path / "metrics.json")

        self.storage_path = storage_path
        self.metrics: Dict = {
            "classifications": [],
            "corrections": [],
            "api_calls": [],
            "rules_triggered": [],
            "errors": [],
            "start_time": datetime.now().isoformat()
        }
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    self.metrics = json.load(f)
            except Exception as exc:
                _log.warning("Could not load metrics file %s: %s", self.storage_path, exc)

    def _save(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.metrics, f, indent=2)

    def record_classification(self, category: str, confidence: float, source: str = "api"):
        with self._lock:
            self.metrics["classifications"].append({
                "category": category,
                "confidence": confidence,
                "source": source,
                "timestamp": datetime.now().isoformat()
            })
            self._cleanup("classifications", 1000)
            self._save()

    def record_correction(self, predicted: str, actual: str):
        with self._lock:
            self.metrics["corrections"].append({
                "predicted": predicted,
                "actual": actual,
                "correct": predicted.lower() == actual.lower(),
                "timestamp": datetime.now().isoformat()
            })
            self._cleanup("corrections", 500)
            self._save()

    def record_api_call(self, endpoint: str, method: str, status: int):
        with self._lock:
            self.metrics["api_calls"].append({
                "endpoint": endpoint,
                "method": method,
                "status": status,
                "timestamp": datetime.now().isoformat()
            })
            self._cleanup("api_calls", 1000)
            self._save()

    def record_rule_triggered(self, rule_name: str, action: str):
        with self._lock:
            self.metrics["rules_triggered"].append({
                "rule": rule_name,
                "action": action,
                "timestamp": datetime.now().isoformat()
            })
            self._cleanup("rules_triggered", 500)
            self._save()

    def record_error(self, error_type: str, message: str):
        with self._lock:
            self.metrics["errors"].append({
                "type": error_type,
                "message": message[:200],
                "timestamp": datetime.now().isoformat()
            })
            self._cleanup("errors", 100)
            self._save()

    def _cleanup(self, key: str, max_items: int):
        if len(self.metrics[key]) > max_items:
            self.metrics[key] = self.metrics[key][-max_items:]

    def get_summary(self) -> Dict:
        with self._lock:
            classifications = self.metrics.get("classifications", [])
            corrections = self.metrics.get("corrections", [])
            api_calls = self.metrics.get("api_calls", [])
            rules = self.metrics.get("rules_triggered", [])
            errors = self.metrics.get("errors", [])

            category_counts = defaultdict(int)
            for c in classifications:
                category_counts[c.get("category", "Unknown")] += 1

            avg_confidence = 0
            if classifications:
                avg_confidence = sum(c.get("confidence", 0) for c in classifications) / len(classifications)

            correction_rate = 0
            if classifications and corrections:
                correction_rate = len(corrections) / len(classifications)

            return {
                "total_classifications": len(classifications),
                "total_corrections": len(corrections),
                "correction_rate": round(correction_rate * 100, 2),
                "avg_confidence": round(avg_confidence * 100, 1),
                "total_api_calls": len(api_calls),
                "total_rules_triggered": len(rules),
                "total_errors": len(errors),
                "category_distribution": dict(category_counts),
                "uptime": self._calculate_uptime()
            }

    def get_category_stats(self) -> Dict:
        with self._lock:
            classifications = self.metrics.get("classifications", [])

            stats = {}
            for c in classifications:
                cat = c.get("category", "Unknown")
                if cat not in stats:
                    stats[cat] = {"count": 0, "total_confidence": 0, "avg_confidence": 0}

                stats[cat]["count"] += 1
                stats[cat]["total_confidence"] += c.get("confidence", 0)

            for cat in stats:
                if stats[cat]["count"] > 0:
                    stats[cat]["avg_confidence"] = round(
                        stats[cat]["total_confidence"] / stats[cat]["count"] * 100, 1
                    )

            return stats

    def get_accuracy(self, days: int = 7) -> Dict:
        with self._lock:
            corrections = self.metrics.get("corrections", [])
            cutoff = datetime.now() - timedelta(days=days)

            recent = [
                c for c in corrections
                if datetime.fromisoformat(c["timestamp"]) > cutoff
            ]

            if not recent:
                return {"accuracy": 100, "total": 0, "correct": 0}

            correct = sum(1 for c in recent if c.get("correct", False))
            total = len(recent)

            return {
                "accuracy": round((correct / total) * 100, 1) if total > 0 else 100,
                "correct": correct,
                "total": total,
                "period_days": days
            }

    def get_api_usage(self, days: int = 1) -> Dict:
        with self._lock:
            api_calls = self.metrics.get("api_calls", [])
            cutoff = datetime.now() - timedelta(days=days)

            recent = [
                c for c in api_calls
                if datetime.fromisoformat(c["timestamp"]) > cutoff
            ]

            endpoint_counts = defaultdict(int)
            for call in recent:
                endpoint_counts[call.get("endpoint", "unknown")] += 1

            return {
                "total_calls": len(recent),
                "endpoints": dict(endpoint_counts),
                "period_days": days
            }

    def _calculate_uptime(self) -> str:
        try:
            start = datetime.fromisoformat(self.metrics.get("start_time", datetime.now().isoformat()))
            delta = datetime.now() - start
            hours = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            return f"{hours}h {minutes}m"
        except Exception as exc:
            _log.debug("metrics uptime parse failed: %s", exc)
            return "unknown"

    def reset(self):
        with self._lock:
            self.metrics = {
                "classifications": [],
                "corrections": [],
                "api_calls": [],
                "rules_triggered": [],
                "errors": [],
                "start_time": datetime.now().isoformat()
            }
            self._save()


metrics_collector = MetricsCollector()


def record_classification(category: str, confidence: float, source: str = "api"):
    metrics_collector.record_classification(category, confidence, source)


def record_correction(predicted: str, actual: str):
    metrics_collector.record_correction(predicted, actual)


def get_metrics_summary() -> Dict:
    return metrics_collector.get_summary()
