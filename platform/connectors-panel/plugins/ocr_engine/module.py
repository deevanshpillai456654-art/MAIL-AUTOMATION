"""
OCR Engine Connector Plugin

Bridges to the existing platform OCR pipeline at platform/plugins/ocr/.
Falls back to Google Vision, AWS Textract, or Azure Form Recognizer when configured.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Optional

from ...sdk.plugin_sdk import ConnectorPlugin, ConnectorSyncResult


class OCREngineConnector(ConnectorPlugin):
    """
    OCR Engine connector.

    Priority order for OCR processing:
    1. Platform internal OCR pipeline (platform/plugins/ocr/)
    2. Google Cloud Vision API  (if GOOGLE_VISION_API_KEY is set)
    3. AWS Textract             (if AWS_ACCESS_KEY_ID is set)
    4. Azure Form Recognizer    (if AZURE_OCR_KEY is set)
    """

    @property
    def plugin_id(self) -> str:
        return "ocr_engine_connector"

    @property
    def name(self) -> str:
        return "OCR Engine"

    @property
    def version(self) -> str:
        return "1.1.0"

    @property
    def category(self) -> str:
        return "ocr"

    # ------------------------------------------------------------------
    # Engine selection
    # ------------------------------------------------------------------

    def _get_engine(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("ocr_engine") or os.environ.get("OCR_ENGINE", "internal")

    def _get_confidence_threshold(self, config: Optional[dict] = None) -> float:
        return float((config or {}).get("confidence_threshold", 0.85))

    # ------------------------------------------------------------------
    # Main OCR method
    # ------------------------------------------------------------------

    def process_document(
        self,
        document_path: str,
        tenant_id: str,
        document_type: str = "invoice",
        config: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Process a document through OCR and return extracted text and fields.

        Args:
            document_path: Local file path or URL to the document
            tenant_id:     Tenant requesting the processing
            document_type: Type hint ("invoice", "receipt", "contract", "general")
            config:        Optional config override

        Returns:
            {
                "success": bool,
                "engine": str,
                "text": str,
                "confidence": float,
                "fields": dict,
                "pages": int,
                "document_path": str,
            }
        """
        engine = self._get_engine(config)
        result: dict[str, Any] = {
            "success": False,
            "engine": engine,
            "text": "",
            "confidence": 0.0,
            "fields": {},
            "pages": 0,
            "document_path": document_path,
        }

        try:
            if engine == "internal":
                ocr_result = self._process_internal(document_path, tenant_id, document_type)
            elif engine == "google_vision":
                ocr_result = self._process_google_vision(document_path, config)
            elif engine == "aws_textract":
                ocr_result = self._process_aws_textract(document_path, config)
            elif engine == "azure_form_recognizer":
                ocr_result = self._process_azure(document_path, config)
            else:
                ocr_result = self._process_internal(document_path, tenant_id, document_type)

            result.update(ocr_result)
            result["success"] = True

        except Exception as exc:
            result["error"] = str(exc)
            result["success"] = False
            self._log("ERROR", f"OCR processing failed: {exc}", tenant_id)

        # Publish event
        event_type = "ocr.document.processed" if result["success"] else "ocr.document.failed"
        self._publish_event(event_type, tenant_id, result)

        return result

    # ------------------------------------------------------------------
    # Internal OCR pipeline bridge
    # ------------------------------------------------------------------

    def _process_internal(
        self,
        document_path: str,
        tenant_id: str,
        document_type: str,
    ) -> dict[str, Any]:
        """Bridge to platform/plugins/ocr/ pipeline."""
        # Attempt to import the platform OCR plugin
        try:
            ocr_mod = importlib.import_module("platform.plugins.ocr.module")
            # Look for a process_document function or OCR class
            if hasattr(ocr_mod, "process_document"):
                return ocr_mod.process_document(document_path, tenant_id, document_type)
            # Try to find and instantiate the OCR class
            for attr_name in dir(ocr_mod):
                cls = getattr(ocr_mod, attr_name)
                if isinstance(cls, type) and hasattr(cls, "process"):
                    instance = cls()
                    return instance.process(document_path, tenant_id)
        except (ImportError, ModuleNotFoundError):
            pass

        # Fallback: basic text extraction using Python stdlib
        return self._process_local_fallback(document_path)

    def _process_local_fallback(self, document_path: str) -> dict[str, Any]:
        """Basic text extraction fallback without external dependencies."""
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        suffix = path.suffix.lower()
        text = ""

        if suffix == ".txt":
            text = path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(str(path)) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                    pages = len(pdf.pages)
            except ImportError:
                text = "[PDF processing requires pdfplumber: pip install pdfplumber]"
                pages = 0
        elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(str(path))
                text = pytesseract.image_to_string(img)
            except ImportError:
                text = "[Image OCR requires pytesseract and Pillow: pip install pytesseract Pillow]"
        else:
            text = f"[Unsupported file format: {suffix}]"

        return {
            "text": text,
            "confidence": 0.9 if text and not text.startswith("[") else 0.0,
            "pages": locals().get("pages", 1),
            "fields": self._extract_invoice_fields(text),
        }

    def _extract_invoice_fields(self, text: str) -> dict[str, Any]:
        """
        Heuristic extraction of common invoice fields from OCR text.
        Returns a dict of extracted fields.
        """
        import re
        fields: dict[str, Any] = {}

        # Invoice number
        inv_match = re.search(r"invoice\s*#?\s*[:.]?\s*([A-Z0-9-]+)", text, re.IGNORECASE)
        if inv_match:
            fields["invoice_number"] = inv_match.group(1).strip()

        # Total amount
        total_match = re.search(r"(?:total|amount due|grand total)\s*[:$]?\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
        if total_match:
            fields["total_amount"] = total_match.group(1).replace(",", "")

        # Date
        date_match = re.search(r"(?:date|invoice date)\s*[:.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text, re.IGNORECASE)
        if date_match:
            fields["invoice_date"] = date_match.group(1)

        # Due date
        due_match = re.search(r"(?:due date|payment due)\s*[:.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text, re.IGNORECASE)
        if due_match:
            fields["due_date"] = due_match.group(1)

        return fields

    # ------------------------------------------------------------------
    # Google Vision
    # ------------------------------------------------------------------

    def _process_google_vision(self, document_path: str, config: Optional[dict] = None) -> dict[str, Any]:
        api_key = (config or {}).get("api_key") or os.environ.get("GOOGLE_VISION_API_KEY", "")
        if not api_key:
            raise ValueError("GOOGLE_VISION_API_KEY not configured")

        import base64
        import httpx
        with open(document_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        response = httpx.post(
            f"https://vision.googleapis.com/v1/images:annotate?key={api_key}",
            json={
                "requests": [{
                    "image": {"content": image_data},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }]
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        annotations = data["responses"][0].get("fullTextAnnotation", {})
        text = annotations.get("text", "")
        return {
            "text": text,
            "confidence": 0.95,
            "pages": len(annotations.get("pages", [])),
            "fields": self._extract_invoice_fields(text),
        }

    # ------------------------------------------------------------------
    # AWS Textract
    # ------------------------------------------------------------------

    def _process_aws_textract(self, document_path: str, config: Optional[dict] = None) -> dict[str, Any]:
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 required for AWS Textract: pip install boto3")

        with open(document_path, "rb") as f:
            doc_bytes = f.read()

        client = boto3.client(
            "textract",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        response = client.detect_document_text(Document={"Bytes": doc_bytes})
        text = " ".join(
            block["Text"]
            for block in response.get("Blocks", [])
            if block["BlockType"] == "LINE"
        )
        return {
            "text": text,
            "confidence": 0.95,
            "pages": 1,
            "fields": self._extract_invoice_fields(text),
        }

    # ------------------------------------------------------------------
    # Azure Form Recognizer
    # ------------------------------------------------------------------

    def _process_azure(self, document_path: str, config: Optional[dict] = None) -> dict[str, Any]:
        endpoint = os.environ.get("AZURE_OCR_ENDPOINT", "")
        api_key = (config or {}).get("api_key") or os.environ.get("AZURE_OCR_KEY", "")
        if not endpoint or not api_key:
            raise ValueError("AZURE_OCR_ENDPOINT and AZURE_OCR_KEY must be configured")

        import httpx
        with open(document_path, "rb") as f:
            doc_bytes = f.read()

        suffix = Path(document_path).suffix.lower().strip(".")
        content_type = "application/pdf" if suffix == "pdf" else f"image/{suffix}"

        response = httpx.post(
            f"{endpoint}/formrecognizer/documentModels/prebuilt-invoice:analyze?api-version=2023-07-31",
            headers={"Ocp-Apim-Subscription-Key": api_key, "Content-Type": content_type},
            content=doc_bytes,
            timeout=120.0,
        )
        response.raise_for_status()

        # Polling would be needed for async; simplified here
        return {
            "text": "[Azure Form Recognizer result — check operation-location header for async result]",
            "confidence": 0.95,
            "pages": 1,
            "fields": {},
            "operation_location": response.headers.get("operation-location", ""),
        }

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    def _publish_event(self, event_type: str, tenant_id: str, payload: dict) -> None:
        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            loop.run_until_complete(bus.publish(event_type, self.plugin_id, tenant_id, payload))
            loop.close()
        except Exception:
            pass

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        engine = self._get_engine()
        if engine == "internal":
            # Check if platform OCR module is available
            try:
                importlib.import_module("platform.plugins.ocr.module")
                return {"status": "ok", "message": "Internal OCR pipeline available", "engine": engine}
            except ImportError:
                return {"status": "degraded", "message": "Internal OCR not available; check pytesseract/pdfplumber", "engine": engine}
        return {"status": "ok", "message": f"OCR engine '{engine}' configured", "engine": engine}

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        engine = self._get_engine(config)
        if engine == "internal":
            return True
        api_key = config.get("api_key") or os.environ.get(f"{engine.upper()}_API_KEY", "")
        return bool(api_key)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ocr_engine": {
                    "type": "string",
                    "enum": ["internal", "google_vision", "aws_textract", "azure_form_recognizer"],
                    "default": "internal",
                },
                "api_key": {"type": "string", "format": "secret"},
                "confidence_threshold": {"type": "number", "default": 0.85},
                "supported_formats": {"type": "array", "items": {"type": "string"}},
            },
        }

    def get_permissions(self) -> list[str]:
        return ["documents.read", "documents.process", "ocr.results.write", "invoices.read"]

    def get_events(self) -> list[str]:
        return ["ocr.document.processed", "ocr.document.failed"]
