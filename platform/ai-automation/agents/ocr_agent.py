"""OCR Agent – bridges to OCR pipeline and AI validation."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAgent


class OCRAgent(BaseAgent):
    agent_type = "ocr"

    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if task_name == "process":
            return await self._process(input_data, tenant_id)
        elif task_name == "validate":
            return await self._validate(input_data)
        elif task_name == "extract_fields":
            return await self._extract_fields(input_data)
        return {"error": f"Unknown OCR task: {task_name}"}

    async def _process(self, data: Dict, tenant_id: Optional[str]) -> Dict:
        try:
            from ...plugins.ocr.pipeline import OCRPipeline
            pipeline = OCRPipeline()
            result = await pipeline.process(
                document_url=data.get("document_url"),
                document_base64=data.get("document_base64"),
            )
            return {"ocr": result, "success": True}
        except Exception as exc:
            return {"error": str(exc), "success": False}

    async def _validate(self, data: Dict) -> Dict:
        ocr_result = data.get("ocr", {})
        confidence = ocr_result.get("confidence", 0)
        needs_review = confidence < 0.7
        return {
            "valid": not needs_review,
            "confidence": confidence,
            "needs_review": needs_review,
            "reason": "Low confidence" if needs_review else None,
        }

    async def _extract_fields(self, data: Dict) -> Dict:
        text = data.get("text", "")
        fields = data.get("fields", [])
        if not text or not fields:
            return {"extracted": {}}
        from ..ai.provider import get_registry
        try:
            registry = get_registry()
            prov = registry.get()
            extracted = await prov.extract(text, fields)
            return {"extracted": extracted}
        except Exception as exc:
            return {"extracted": {}, "error": str(exc)}
