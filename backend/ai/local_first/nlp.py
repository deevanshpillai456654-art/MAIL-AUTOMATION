"""Lightweight local NLP pipelines built on the v9.7 runtime.

This layer provides stable product APIs for classification, extraction, smart
routing, tagging, priority detection, and workflow suggestions without adding
heavy LLM or cloud dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .cache import get_ai_cache
from .runtime import get_runtime
from .telemetry import get_ai_telemetry


class LightweightNLPPipeline:
    def _run_cached(self, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        cache = get_ai_cache()
        cached = cache.get(task, payload)
        if cached is not None:
            get_ai_telemetry().record("cache_hit", "nlp", "ok", metadata={"task": task})
            return cached
        result = get_runtime().infer(task, payload)
        value = result.output
        cache.set(task, payload, value)
        get_ai_telemetry().record("inference", "nlp", "ok", result.latency_ms, {"task": task, "engine": result.engine})
        return value

    def classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._run_cached("classify_email", payload)

    def extract(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._run_cached("extract_entities", payload)

    def priority(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        classified = self.classify(payload)
        category = classified.get("category", "Personal")
        return {
            "priority": classified.get("priority", "normal"),
            "category": category,
            "score": 0.9 if category in {"OTP", "Security", "Finance"} else 0.55,
        }

    def smart_tags(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        classified = self.classify(payload)
        extracted = self.extract(payload)
        tags: List[str] = [str(classified.get("category", "Personal"))]
        if extracted.get("amounts"):
            tags.append("has_amount")
        if extracted.get("tracking_refs"):
            tags.append("has_tracking")
        if classified.get("priority") == "high":
            tags.append("high_priority")
        return {"tags": sorted(set(tag for tag in tags if tag)), "classification": classified, "entities": extracted}

    def workflow_suggestion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._run_cached("detect_workflow", payload)


_pipeline: LightweightNLPPipeline | None = None


def get_nlp_pipeline() -> LightweightNLPPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = LightweightNLPPipeline()
    return _pipeline
