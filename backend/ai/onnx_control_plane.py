"""Local ONNX AI control plane with learning and self-healing fallback.

The control plane is deliberately local-first. Real .onnx models are used when
ONNX Runtime is installed and a compatible model is present. When either part is
missing or unhealthy, the existing deterministic classifier remains the safe
runtime and user feedback still improves future decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from backend import config
from backend.ai.classifier import EmailClassifier
from backend.runtime_version import APP_VERSION

try:  # pragma: no cover - optional native runtime
    import onnxruntime as ort  # type: ignore
except Exception:  # noqa: BLE001
    ort = None


DEFAULT_LABELS = [
    "Finance",
    "OTP",
    "Clients",
    "Personal",
    "Promotions",
    "Spam",
    "Newsletters",
    "Trading",
    "Logistics",
    "Purchases",
    "HR",
    "Support",
    "Bills",
    "Security",
    "Scam",
    "Normal",
    "Marketing",
    "Sales",
    "Social Media",
    "Investor",
    "Leads",
]

DEFAULT_EVALUATION_CASES = [
    {
        "subject": "Investor update",
        "sender_email": "founder@example.com",
        "body": "Investor diligence and board update.",
        "expected_category": "Investor",
    },
    {
        "subject": "Sales lead",
        "sender_email": "lead@example.com",
        "body": "New sales opportunity and demo request.",
        "expected_category": "Sales",
    },
    {
        "subject": "Support ticket",
        "sender_email": "customer@example.com",
        "body": "Please help resolve this support issue.",
        "expected_category": "Support",
    },
    {
        "subject": "Suspicious account alert",
        "sender_email": "security@example.com",
        "body": "Verify your account immediately to avoid suspension.",
        "expected_category": "Scam",
    },
]


def _now() -> float:
    return time.time()


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain(sender_email: str) -> str:
    value = (sender_email or "").strip().lower()
    return value.rsplit("@", 1)[-1] if "@" in value else ""


class OnnxAIControlPlane:
    """Model registry, local inference, adaptive feedback, and fallback health."""

    def __init__(self, model_dir: Optional[str] = None) -> None:
        self.model_dir = Path(model_dir or config.MODEL_DIR)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.model_dir / "onnx_model_registry.json"
        self.learning_path = self.model_dir / "onnx_learning_memory.json"
        self.healing_path = self.model_dir / "onnx_self_healing.json"
        self.backup_dir = self.model_dir / "onnx_ai_backups"
        self.backup_index_path = self.backup_dir / "index.json"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._classifier = EmailClassifier()
        self._sessions: Dict[str, Any] = {}
        self._registry = _read_json(self.registry_path, {"models": {}, "active_model": None})
        self._learning = _read_json(self.learning_path, {"overrides": {}, "corrections": [], "stats": {}})
        self._healing = _read_json(self.healing_path, {"events": [], "fallback_forced": False})
        self._backups = _read_json(
            self.backup_index_path,
            {
                "backups": [],
                "schedule": {
                    "enabled": True,
                    "interval_seconds": 86400,
                    "retention": 7,
                    "last_backup_at": 0,
                },
            },
        )

    @property
    def runtime_available(self) -> bool:
        return ort is not None

    def discover_models(self) -> List[Dict[str, Any]]:
        with self._lock:
            models = self._registry.setdefault("models", {})
            for model_path in sorted(self.model_dir.rglob("*.onnx")):
                if not model_path.is_file():
                    continue
                name = model_path.stem
                checksum = _sha256(model_path)
                existing = models.get(name, {})
                checksum_changed = existing and existing.get("checksum_sha256") != checksum
                labels = self._load_labels(model_path)
                record = {
                    **existing,
                    "name": name,
                    "path": str(model_path),
                    "checksum_sha256": checksum,
                    "size_bytes": model_path.stat().st_size,
                    "labels": labels,
                    "engine": "onnxruntime",
                    "runtime_available": self.runtime_available,
                    "healthy": bool(existing.get("healthy", True)) and not checksum_changed,
                    "quarantined": bool(existing.get("quarantined", False)) or checksum_changed,
                    "activation_accepted": bool(existing.get("activation_accepted", False)) and not checksum_changed,
                    "updated_at": _now(),
                }
                if checksum_changed:
                    record["quarantine_reason"] = "checksum_changed"
                    record["activation_blocked_reason"] = "checksum_changed_requires_evaluation"
                    self._append_event("quarantine_model", name, "checksum_changed")
                models[name] = record
            self._select_active_model()
            self._save_all()
            return self._model_list()

    def _load_labels(self, model_path: Path) -> List[str]:
        for sidecar in (model_path.with_suffix(".labels.json"), model_path.with_suffix(".json")):
            if not sidecar.exists():
                continue
            payload = _read_json(sidecar, {})
            labels = payload.get("labels") if isinstance(payload, dict) else None
            if isinstance(labels, list) and all(isinstance(item, str) for item in labels):
                return labels
        return DEFAULT_LABELS

    def validate_model(self, model_name: str) -> Dict[str, Any]:
        with self._lock:
            self.discover_models()
            record = self._registry.get("models", {}).get(model_name)
            if not record:
                return {"valid": False, "reason": "model_not_registered"}
            path = Path(record["path"])
            if not path.exists():
                return self.report_model_failure(model_name, "model_file_missing")
            if path.suffix.lower() != ".onnx":
                return self.report_model_failure(model_name, "unsupported_model_format")
            if not self.runtime_available:
                record["runtime_available"] = False
                record["healthy"] = True
                self._save_all()
                return {"valid": True, "runtime_loadable": False, "reason": "onnxruntime_not_installed"}
            try:
                self._session_for(record)
            except Exception as exc:  # noqa: BLE001
                return self.report_model_failure(model_name, f"load_error:{exc}")
            record["healthy"] = True
            record["quarantined"] = False
            record.pop("quarantine_reason", None)
            self._select_active_model()
            self._save_all()
            return {"valid": True, "runtime_loadable": True, "checksum_sha256": record["checksum_sha256"]}

    def evaluate_model(
        self,
        model_name: str,
        cases: Optional[List[Dict[str, Any]]] = None,
        min_accuracy: float = 0.8,
        activate: bool = False,
    ) -> Dict[str, Any]:
        """Evaluate a registered model and optionally activate it if it passes."""
        model_name = str(model_name or "").strip()
        threshold = max(0.0, min(1.0, float(min_accuracy)))
        with self._lock:
            self.discover_models()
            validation = self.validate_model(model_name)
            record = self._registry.get("models", {}).get(model_name)
            if not record:
                return {
                    "status": "blocked",
                    "model": model_name,
                    "reason": "model_not_registered",
                    "activated": False,
                    "validation": validation,
                }
            if not validation.get("valid"):
                return self._store_evaluation_result(
                    record,
                    {
                        "status": "blocked",
                        "model": model_name,
                        "reason": validation.get("reason") or validation.get("status") or "validation_failed",
                        "activated": False,
                        "validation": validation,
                        "min_accuracy": threshold,
                    },
                )
            if not self.runtime_available or not validation.get("runtime_loadable", False):
                return self._store_evaluation_result(
                    record,
                    {
                        "status": "blocked",
                        "model": model_name,
                        "reason": validation.get("reason") or "onnxruntime_not_available",
                        "activated": False,
                        "validation": validation,
                        "min_accuracy": threshold,
                    },
                )

            evaluation_cases = self._normalize_evaluation_cases(cases)
            if not evaluation_cases:
                return self._store_evaluation_result(
                    record,
                    {
                        "status": "blocked",
                        "model": model_name,
                        "reason": "evaluation_cases_required",
                        "activated": False,
                        "validation": validation,
                        "min_accuracy": threshold,
                    },
                )

            predictions = []
            correct = 0
            for case in evaluation_cases:
                result = self._classify_with_onnx(record, case["payload"])
                predicted = result.get("category") or ""
                expected = case["expected_category"]
                passed = predicted == expected
                if passed:
                    correct += 1
                predictions.append({
                    "expected_category": expected,
                    "predicted_category": predicted,
                    "passed": passed,
                    "confidence": result.get("confidence"),
                    "subject": case["payload"].get("subject", ""),
                })

            total = len(evaluation_cases)
            accuracy = correct / total if total else 0.0
            accepted = accuracy >= threshold
            activated = bool(activate and accepted)
            if accepted:
                record["healthy"] = True
                record["quarantined"] = False
                record["activation_accepted"] = True
                record.pop("activation_blocked_reason", None)
                record.pop("quarantine_reason", None)
                if activated:
                    self._registry["active_model"] = model_name
                    self._append_event("activate_model", model_name, f"accuracy:{accuracy:.4f}")
            else:
                record["activation_accepted"] = False
                record["activation_blocked_reason"] = "accuracy_below_threshold"
                if self._registry.get("active_model") == model_name:
                    self._registry["active_model"] = None
                self._select_active_model()

            return self._store_evaluation_result(
                record,
                {
                    "status": "accepted" if accepted else "rejected",
                    "model": model_name,
                    "checksum_sha256": record.get("checksum_sha256"),
                    "accuracy": round(accuracy, 4),
                    "correct": correct,
                    "total": total,
                    "min_accuracy": threshold,
                    "accepted": accepted,
                    "activated": activated,
                    "predictions": predictions,
                    "validation": validation,
                },
            )

    def classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self.discover_models()
            learned = self._learned_override(payload)
            if learned:
                return learned
            record = self._active_record()
            if record and self.runtime_available:
                try:
                    return self._classify_with_onnx(record, payload)
                except Exception as exc:  # noqa: BLE001
                    self.report_model_failure(record["name"], f"inference_error:{exc}")
            return self._classify_with_fallback(payload)

    def record_feedback(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        sender_email = str(feedback.get("sender_email") or "").strip().lower()
        sender = str(feedback.get("sender") or "").strip().lower()
        actual = str(feedback.get("actual_category") or feedback.get("category") or "").strip()
        predicted = str(feedback.get("predicted_category") or "").strip()
        priority = str(feedback.get("priority") or ("Critical" if actual == "Scam" else "Medium")).strip()
        scope = str(feedback.get("scope") or "sender").strip().lower()
        if not actual:
            return {"status": "ignored", "reason": "actual_category_required"}
        if not sender_email and not sender:
            return {"status": "ignored", "reason": "sender_required"}

        if scope == "domain" and _domain(sender_email):
            key = f"domain:{_domain(sender_email)}"
        else:
            key = f"sender:{sender_email or sender}"
        with self._lock:
            overrides = self._learning.setdefault("overrides", {})
            existing = overrides.get(key, {})
            overrides[key] = {
                "category": actual,
                "priority": priority,
                "confidence": float(feedback.get("confidence") or existing.get("confidence") or 0.97),
                "predicted_category": predicted,
                "scope": scope,
                "hits": int(existing.get("hits", 0)),
                "updated_at": _now(),
            }
            corrections = self._learning.setdefault("corrections", [])
            corrections.append({
                "key": key,
                "action": "learned",
                "predicted_category": predicted,
                "actual_category": actual,
                "priority": priority,
                "created_at": _now(),
            })
            del corrections[:-500]
            stats = self._learning.setdefault("stats", {})
            stats["corrections_total"] = int(stats.get("corrections_total", 0)) + 1
            stats["last_correction_at"] = _now()
            self._save_all()
            return {"status": "learned", "key": key, "category": actual, "priority": priority}

    def report_model_failure(self, model_name: str, reason: str) -> Dict[str, Any]:
        with self._lock:
            record = self._registry.setdefault("models", {}).get(model_name)
            if record:
                record["healthy"] = False
                record["quarantined"] = True
                record["quarantine_reason"] = reason
                record["failure_count"] = int(record.get("failure_count", 0)) + 1
            self._sessions.pop(model_name, None)
            if self._registry.get("active_model") == model_name:
                self._registry["active_model"] = None
            self._append_event("quarantine_model", model_name, reason)
            self._select_active_model()
            self._save_all()
            return {
                "status": "quarantined",
                "model": model_name,
                "reason": reason,
                "active_model": self._registry.get("active_model"),
                "fallback_active": self._fallback_active(),
            }

    def recover_model(self, model_name: str) -> Dict[str, Any]:
        """Revalidate and reactivate a quarantined model after repair."""
        with self._lock:
            validation = self.validate_model(model_name)
            if not validation.get("valid"):
                return {
                    "status": "not_recovered",
                    "model": model_name,
                    "reason": validation.get("reason") or validation.get("status") or "validation_failed",
                    "validation": validation,
                    "active_model": self._registry.get("active_model"),
                    "fallback_active": self._fallback_active(),
                }

            record = self._registry.get("models", {}).get(model_name)
            if not record:
                return {
                    "status": "not_recovered",
                    "model": model_name,
                    "reason": "model_not_registered",
                    "validation": validation,
                    "active_model": self._registry.get("active_model"),
                    "fallback_active": self._fallback_active(),
                }

            record["healthy"] = True
            record["quarantined"] = False
            record.pop("quarantine_reason", None)
            if self.runtime_available and validation.get("runtime_loadable", False) and record.get("activation_accepted"):
                self._registry["active_model"] = model_name
            else:
                self._select_active_model()
            self._append_event("recover_model", model_name, "manual_recovery")
            self._save_all()
            return {
                "status": "recovered" if not self._fallback_active() else "validated_fallback",
                "model": model_name,
                "validation": validation,
                "active_model": self._registry.get("active_model"),
                "fallback_active": self._fallback_active(),
            }

    def learning_stats(self) -> Dict[str, Any]:
        overrides = self._learning.get("overrides", {})
        stats = dict(self._learning.get("stats", {}))
        stats.update({
            "learned_overrides": len(overrides),
            "corrections_retained": len(self._learning.get("corrections", [])),
        })
        return stats

    def learning_overrides(self) -> Dict[str, Any]:
        with self._lock:
            overrides = self._learning.get("overrides", {})
            items = []
            for key, item in overrides.items():
                record = dict(item)
                record["key"] = key
                items.append(record)
            items.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
            return {"total": len(items), "items": items, "stats": self.learning_stats()}

    def learning_events(self, limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            corrections = list(self._learning.get("corrections", []))
            items = []
            for raw in reversed(corrections):
                if not isinstance(raw, dict):
                    continue
                event = dict(raw)
                event["action"] = event.get("action") or "learned"
                event["actual_category"] = event.get("actual_category") or event.get("category") or ""
                event["priority"] = event.get("priority") or ""
                event["created_at"] = float(event.get("created_at") or 0)
                items.append(event)
            return {
                "total": len(corrections),
                "items": items[:limit],
                "stats": self.learning_stats(),
            }

    def forget_learning_override(self, key: str) -> Dict[str, Any]:
        key = str(key or "").strip()
        if not key:
            return {"status": "ignored", "reason": "key_required"}
        with self._lock:
            overrides = self._learning.setdefault("overrides", {})
            removed = overrides.pop(key, None)
            if removed is None:
                return {"status": "not_found", "key": key}
            corrections = self._learning.setdefault("corrections", [])
            corrections.append({
                "key": key,
                "action": "forgotten",
                "predicted_category": removed.get("predicted_category", ""),
                "actual_category": removed.get("category", ""),
                "priority": removed.get("priority", ""),
                "created_at": _now(),
            })
            del corrections[:-500]
            stats = self._learning.setdefault("stats", {})
            stats["forgotten_overrides_total"] = int(stats.get("forgotten_overrides_total", 0)) + 1
            stats["last_forget_at"] = _now()
            self._save_all()
            return {"status": "forgotten", "key": key, "removed": removed, "stats": self.learning_stats()}

    def export_learning_memory(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": 1,
                "exported_at": _now(),
                "app_version": APP_VERSION,
                "overrides": dict(self._learning.get("overrides", {})),
                "corrections": list(self._learning.get("corrections", []))[-500:],
                "stats": dict(self._learning.get("stats", {})),
            }

    def preview_learning_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Review a learning-memory import without changing stored decisions."""
        if not isinstance(payload, dict):
            return {"status": "ignored", "reason": "payload_must_be_object"}
        incoming = payload.get("overrides", {})
        if not isinstance(incoming, dict):
            return {"status": "ignored", "reason": "overrides_must_be_object"}

        replace = bool(payload.get("replace"))
        with self._lock:
            existing_overrides = self._learning.get("overrides", {})
            conflicts: List[Dict[str, Any]] = []
            new_items: List[Dict[str, Any]] = []
            unchanged: List[Dict[str, Any]] = []
            invalid_items: List[Dict[str, Any]] = []
            incoming_keys = set()

            for raw_key, raw_item in incoming.items():
                key = str(raw_key or "").strip()
                normalized = self._normalize_learning_import_item(key, raw_item)
                if not normalized:
                    invalid_items.append({
                        "key": key or str(raw_key or ""),
                        "reason": "invalid_key_or_category",
                    })
                    continue

                incoming_keys.add(key)
                incoming_view = self._learning_import_compare_view(normalized)
                existing = existing_overrides.get(key)
                if existing is None:
                    new_items.append({"key": key, "incoming": incoming_view})
                    continue

                existing_view = self._learning_import_compare_view(existing)
                if existing_view != incoming_view:
                    conflicts.append({
                        "key": key,
                        "existing": existing_view,
                        "incoming": incoming_view,
                    })
                else:
                    unchanged.append({"key": key, "item": incoming_view})

            removed = sorted(existing_key for existing_key in existing_overrides if existing_key not in incoming_keys) if replace else []
            return {
                "status": "review_required" if conflicts or removed else "ready",
                "replace": replace,
                "total_incoming": len(incoming),
                "conflict_count": len(conflicts),
                "new_count": len(new_items),
                "unchanged_count": len(unchanged),
                "invalid_count": len(invalid_items),
                "removed_count": len(removed),
                "conflicts": conflicts[:100],
                "new_items": new_items[:100],
                "unchanged": unchanged[:100],
                "invalid_items": invalid_items[:100],
                "removed_keys": removed[:100],
                "stats": self.learning_stats(),
            }

    def import_learning_memory(self, payload: Dict[str, Any], replace: bool = False) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"status": "ignored", "reason": "payload_must_be_object"}
        incoming = payload.get("overrides", {})
        if not isinstance(incoming, dict):
            return {"status": "ignored", "reason": "overrides_must_be_object"}
        with self._lock:
            overrides = {} if replace else self._learning.setdefault("overrides", {})
            imported = 0
            skipped = 0
            for key, item in incoming.items():
                key = str(key or "").strip()
                if not key or not isinstance(item, dict) or ":" not in key:
                    skipped += 1
                    continue
                category = str(item.get("category") or "").strip()
                if not category:
                    skipped += 1
                    continue
                overrides[key] = {
                    "category": category,
                    "priority": str(item.get("priority") or ("Critical" if category == "Scam" else "Medium")).strip(),
                    "confidence": float(item.get("confidence") or 0.97),
                    "predicted_category": str(item.get("predicted_category") or "").strip(),
                    "scope": str(item.get("scope") or key.split(":", 1)[0]).strip(),
                    "hits": int(item.get("hits") or 0),
                    "updated_at": float(item.get("updated_at") or _now()),
                }
                self._learning.setdefault("corrections", []).append({
                    "key": key,
                    "action": "imported",
                    "predicted_category": str(item.get("predicted_category") or "").strip(),
                    "actual_category": category,
                    "priority": overrides[key]["priority"],
                    "created_at": _now(),
                })
                imported += 1
            corrections = self._learning.setdefault("corrections", [])
            del corrections[:-500]
            if replace:
                self._learning["overrides"] = overrides
            stats = self._learning.setdefault("stats", {})
            stats["imported_overrides_total"] = int(stats.get("imported_overrides_total", 0)) + imported
            stats["last_import_at"] = _now()
            self._save_all()
            return {
                "status": "imported",
                "imported_overrides": imported,
                "skipped_overrides": skipped,
                "replace": replace,
                "stats": self.learning_stats(),
            }

    def _normalize_learning_import_item(self, key: str, item: Any) -> Optional[Dict[str, Any]]:
        key = str(key or "").strip()
        if not key or ":" not in key or not isinstance(item, dict):
            return None
        category = str(item.get("category") or "").strip()
        if not category:
            return None
        try:
            confidence = float(item.get("confidence") or 0.97)
        except (TypeError, ValueError):
            confidence = 0.97
        try:
            hits = int(item.get("hits") or 0)
        except (TypeError, ValueError):
            hits = 0
        return {
            "category": category,
            "priority": str(item.get("priority") or ("Critical" if category == "Scam" else "Medium")).strip(),
            "confidence": confidence,
            "predicted_category": str(item.get("predicted_category") or "").strip(),
            "scope": str(item.get("scope") or key.split(":", 1)[0]).strip(),
            "hits": hits,
        }

    def _learning_import_compare_view(self, item: Dict[str, Any]) -> Dict[str, Any]:
        category = str(item.get("category") or "").strip()
        try:
            confidence = round(float(item.get("confidence") or 0.97), 4)
        except (TypeError, ValueError):
            confidence = 0.97
        return {
            "category": category,
            "priority": str(item.get("priority") or ("Critical" if category == "Scam" else "Medium")).strip(),
            "scope": str(item.get("scope") or "sender").strip(),
            "predicted_category": str(item.get("predicted_category") or "").strip(),
            "confidence": confidence,
        }

    def create_ai_state_backup(self, reason: str = "manual") -> Dict[str, Any]:
        """Snapshot model registry, learning memory, and self-healing state."""
        with self._lock:
            self._save_all()
            backups = self._backups.setdefault("backups", [])
            backup_id = f"ai_state_{int(_now() * 1000)}_{len(backups) + 1}"
            target = self.backup_dir / backup_id
            target.mkdir(parents=True, exist_ok=True)

            files: Dict[str, Dict[str, Any]] = {}
            for name, source in self._ai_state_files().items():
                record = {"exists": source.exists(), "size_bytes": 0, "checksum_sha256": ""}
                if source.exists():
                    destination = target / name
                    shutil.copy2(source, destination)
                    record["size_bytes"] = destination.stat().st_size
                    record["checksum_sha256"] = _sha256(destination)
                files[name] = record

            manifest = {
                "status": "created",
                "backup_id": backup_id,
                "reason": str(reason or "manual"),
                "created_at": _now(),
                "files": files,
                "app_version": APP_VERSION,
            }
            _write_json(target / "manifest.json", manifest)

            backups.insert(0, manifest)
            if manifest["reason"] == "scheduled":
                schedule = self._backups.setdefault("schedule", {})
                schedule["last_backup_at"] = manifest["created_at"]
            self._prune_ai_state_backups()
            self._save_ai_state_backup_index()
            return manifest

    def restore_ai_state_backup(self, backup_id: str) -> Dict[str, Any]:
        backup_id = str(backup_id or "").strip()
        if not backup_id:
            return {"status": "ignored", "reason": "backup_id_required"}
        with self._lock:
            backup = self._find_ai_state_backup(backup_id)
            if not backup:
                return {"status": "not_found", "backup_id": backup_id}

            source_dir = self.backup_dir / backup_id
            manifest_files = backup.get("files", {}) if isinstance(backup.get("files"), dict) else {}
            restored_files = []
            for name, target in self._ai_state_files().items():
                source = source_dir / name
                expected = manifest_files.get(name, {})
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    restored_files.append(name)
                elif expected.get("exists") is False and target.exists():
                    target.unlink()

            self._registry = _read_json(self.registry_path, {"models": {}, "active_model": None})
            self._learning = _read_json(self.learning_path, {"overrides": {}, "corrections": [], "stats": {}})
            self._healing = _read_json(self.healing_path, {"events": [], "fallback_forced": False})
            self._sessions.clear()
            return {
                "status": "restored",
                "backup_id": backup_id,
                "restored_files": restored_files,
                "stats": self.learning_stats(),
            }

    def configure_ai_state_backup_schedule(
        self,
        enabled: bool = True,
        interval_seconds: int = 86400,
        retention: int = 7,
    ) -> Dict[str, Any]:
        interval = max(60, int(interval_seconds or 86400))
        keep = max(1, min(int(retention or 7), 100))
        with self._lock:
            schedule = self._backups.setdefault("schedule", {})
            schedule.update({
                "enabled": bool(enabled),
                "interval_seconds": interval,
                "retention": keep,
                "updated_at": _now(),
            })
            schedule.setdefault("last_backup_at", 0)
            self._prune_ai_state_backups()
            self._save_ai_state_backup_index()
            return dict(schedule)

    def run_scheduled_ai_state_backup(self) -> Dict[str, Any]:
        with self._lock:
            schedule = self._backups.setdefault("schedule", {})
            if not bool(schedule.get("enabled", True)):
                return {"status": "skipped", "reason": "disabled", "schedule": dict(schedule)}
            interval = max(60, int(schedule.get("interval_seconds") or 86400))
            last = float(schedule.get("last_backup_at") or 0)
            now = _now()
            if last and now - last < interval:
                return {
                    "status": "skipped",
                    "reason": "not_due",
                    "next_backup_at": last + interval,
                    "schedule": dict(schedule),
                }
            backup = self.create_ai_state_backup(reason="scheduled")
            return {"status": "created", "backup": backup, "schedule": dict(self._backups.get("schedule", {}))}

    def ai_state_backup_status(self) -> Dict[str, Any]:
        with self._lock:
            backups = sorted(
                [dict(item) for item in self._backups.get("backups", []) if isinstance(item, dict)],
                key=lambda item: float(item.get("created_at") or 0),
                reverse=True,
            )
            return {
                "total_backups": len(backups),
                "backups": backups,
                "schedule": dict(self._backups.get("schedule", {})),
            }

    def _ai_state_files(self) -> Dict[str, Path]:
        return {
            "onnx_model_registry.json": self.registry_path,
            "onnx_learning_memory.json": self.learning_path,
            "onnx_self_healing.json": self.healing_path,
        }

    def _find_ai_state_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        for item in self._backups.get("backups", []):
            if isinstance(item, dict) and item.get("backup_id") == backup_id:
                return item
        manifest = self.backup_dir / backup_id / "manifest.json"
        if manifest.exists():
            value = _read_json(manifest, {})
            return value if value.get("backup_id") == backup_id else None
        return None

    def _prune_ai_state_backups(self) -> None:
        schedule = self._backups.setdefault("schedule", {})
        retention = max(1, min(int(schedule.get("retention") or 7), 100))
        backups = sorted(
            [item for item in self._backups.get("backups", []) if isinstance(item, dict)],
            key=lambda item: float(item.get("created_at") or 0),
            reverse=True,
        )
        keep = backups[:retention]
        drop = backups[retention:]
        for item in drop:
            backup_id = item.get("backup_id")
            if backup_id:
                shutil.rmtree(self.backup_dir / str(backup_id), ignore_errors=True)
        self._backups["backups"] = keep

    def _save_ai_state_backup_index(self) -> None:
        _write_json(self.backup_index_path, self._backups)

    def self_healing_status(self) -> Dict[str, Any]:
        events = list(self._healing.get("events", []))[-50:]
        return {
            "fallback_active": self._fallback_active(),
            "events": events,
            "quarantined_models": [
                name for name, record in self._registry.get("models", {}).items()
                if record.get("quarantined")
            ],
            "active_model": self._registry.get("active_model"),
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self.discover_models()
            fallback = self._fallback_active()
            return {
                "version": APP_VERSION,
                "status": "ready" if not self._registry.get("models") or not fallback else "degraded",
                "mode": "fallback" if fallback else "onnx",
                "runtime_available": self.runtime_available,
                "model_dir": str(self.model_dir),
                "active_model": self._registry.get("active_model"),
                "models": self._model_list(),
                "learning": self.learning_stats(),
                "self_healing": self.self_healing_status(),
            }

    def _learned_override(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sender_email = str(payload.get("sender_email") or "").strip().lower()
        sender = str(payload.get("sender") or "").strip().lower()
        domain = _domain(sender_email)
        keys = [f"sender:{sender_email}", f"sender:{sender}", f"domain:{domain}"]
        overrides = self._learning.get("overrides", {})
        for key in keys:
            if not key or key in {"sender:", "domain:"}:
                continue
            item = overrides.get(key)
            if not item:
                continue
            item["hits"] = int(item.get("hits", 0)) + 1
            self._save_all()
            category = item.get("category") or "Personal"
            return {
                "category": category,
                "confidence": round(float(item.get("confidence") or 0.97), 2),
                "priority": item.get("priority") or ("Critical" if category == "Scam" else "Medium"),
                "source": "learned_override",
                "model": {"name": "adaptive-learning-memory", "engine": "learning_memory"},
                "learning": {"matched": True, "matched_key": key, "scope": item.get("scope", "sender")},
                "self_healing": self.self_healing_status(),
                "timestamp": _now(),
            }
        return None

    def _normalize_evaluation_cases(self, cases: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        raw_cases = cases if cases is not None else DEFAULT_EVALUATION_CASES
        normalized = []
        for raw in raw_cases or []:
            if not isinstance(raw, dict):
                continue
            payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else dict(raw)
            expected = str(
                raw.get("expected_category")
                or raw.get("expected")
                or raw.get("category")
                or payload.pop("expected_category", "")
                or payload.pop("expected", "")
            ).strip()
            payload.pop("category", None)
            if not expected:
                continue
            normalized.append({"payload": payload, "expected_category": expected})
        return normalized

    def _store_evaluation_result(self, record: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        payload = {**result, "evaluated_at": _now()}
        record["last_evaluation"] = {
            key: value for key, value in payload.items()
            if key not in {"predictions", "validation"}
        }
        record["last_evaluation"]["predictions"] = payload.get("predictions", [])[:50]
        self._save_all()
        return payload

    def _classify_with_fallback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._classifier.classify(
            subject=str(payload.get("subject") or ""),
            sender=str(payload.get("sender") or ""),
            sender_email=str(payload.get("sender_email") or ""),
            body=str(payload.get("body") or payload.get("text") or ""),
        )
        return {
            **result,
            "source": "onnx_fallback_rules",
            "model": {
                "name": self._registry.get("active_model") or "rules-fallback",
                "engine": "local_fallback",
                "runtime_available": self.runtime_available,
            },
            "learning": {"matched": False, **self.learning_stats()},
            "self_healing": self.self_healing_status(),
        }

    def _classify_with_onnx(self, record: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._session_for(record)
        input_meta = session.get_inputs()[0]
        width = self._input_width(input_meta)
        vector = self._feature_vector(payload, width).reshape(1, width)
        outputs = session.run(None, {input_meta.name: vector})
        scores = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
        labels = record.get("labels") or DEFAULT_LABELS
        if scores.size == 1:
            confidence = 1.0 / (1.0 + math.exp(-float(scores[0])))
            category = "Scam" if confidence >= 0.5 else "Normal"
        else:
            exp = np.exp(scores - np.max(scores))
            probs = exp / np.sum(exp)
            index = int(np.argmax(probs))
            category = labels[index] if index < len(labels) else f"Class {index}"
            confidence = float(probs[index])
        return {
            "category": category,
            "confidence": round(float(confidence), 2),
            "priority": "Critical" if category == "Scam" else ("High" if category in {"Security", "OTP", "Investor"} else "Medium"),
            "source": "onnx_model",
            "model": {"name": record["name"], "engine": "onnxruntime", "checksum_sha256": record["checksum_sha256"]},
            "learning": {"matched": False, **self.learning_stats()},
            "self_healing": self.self_healing_status(),
            "timestamp": _now(),
        }

    def _session_for(self, record: Dict[str, Any]) -> Any:
        if ort is None:
            raise RuntimeError("onnxruntime_not_installed")
        name = record["name"]
        if name not in self._sessions:
            self._sessions[name] = ort.InferenceSession(record["path"], providers=["CPUExecutionProvider"])
        return self._sessions[name]

    def _input_width(self, input_meta: Any) -> int:
        shape = getattr(input_meta, "shape", None) or [1, 64]
        try:
            width = int(shape[-1])
            return width if width > 0 else 64
        except (TypeError, ValueError):
            return 64

    def _feature_vector(self, payload: Dict[str, Any], width: int) -> np.ndarray:
        text = " ".join(str(payload.get(key, "")) for key in ("subject", "sender", "sender_email", "body", "text")).lower()
        vector = np.zeros(width, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % width
            vector[index] += 1.0 + min(len(token), 16) / 16.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def _active_record(self) -> Optional[Dict[str, Any]]:
        name = self._registry.get("active_model")
        return self._registry.get("models", {}).get(name) if name else None

    def _select_active_model(self) -> None:
        models = self._registry.get("models", {})
        active = self._registry.get("active_model")
        if (
            active
            and models.get(active, {}).get("healthy")
            and not models.get(active, {}).get("quarantined")
            and models.get(active, {}).get("activation_accepted")
        ):
            return
        self._registry["active_model"] = None
        if not self.runtime_available:
            return
        for name, record in sorted(models.items()):
            if record.get("healthy", True) and not record.get("quarantined") and record.get("activation_accepted"):
                self._registry["active_model"] = name
                return

    def _fallback_active(self) -> bool:
        record = self._active_record()
        return not (record and self.runtime_available and record.get("healthy") and not record.get("quarantined"))

    def _model_list(self) -> List[Dict[str, Any]]:
        return list(self._registry.get("models", {}).values())

    def _append_event(self, action: str, model: str, reason: str) -> None:
        events = self._healing.setdefault("events", [])
        event = {"action": action, "model": model, "reason": reason, "created_at": _now()}
        if event not in events[-3:]:
            events.append(event)
        del events[:-200]

    def _save_all(self) -> None:
        _write_json(self.registry_path, self._registry)
        _write_json(self.learning_path, self._learning)
        _write_json(self.healing_path, self._healing)


_control_plane: Optional[OnnxAIControlPlane] = None
_control_plane_lock = threading.Lock()


def get_onnx_control_plane() -> OnnxAIControlPlane:
    global _control_plane
    with _control_plane_lock:
        if _control_plane is None:
            _control_plane = OnnxAIControlPlane()
        return _control_plane


__all__ = ["OnnxAIControlPlane", "get_onnx_control_plane", "DEFAULT_LABELS", "DEFAULT_EVALUATION_CASES"]
