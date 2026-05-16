from __future__ import annotations
import re
from sdk.models import ShipmentReference

AWB_RE = re.compile(r"\b\d{3}[- ]?\d{8}\b")
BL_RE = re.compile(r"\b(?:BL|B/L)[:#\s-]*([A-Z0-9-]{5,30})\b", re.I)
CONTAINER_RE = re.compile(r"\b[A-Z]{4}\d{7}\b")
INVOICE_RE = re.compile(r"\b(?:INVOICE|INV)[:#\s-]*([A-Z0-9/-]{4,30})\b", re.I)

class WhatsAppReferenceDetector:
    def detect(self, text: str) -> ShipmentReference:
        awb_match = AWB_RE.search(text or "")
        bl_match = BL_RE.search(text or "")
        container_match = CONTAINER_RE.search(text or "")
        invoice_match = INVOICE_RE.search(text or "")
        return ShipmentReference(
            awb=awb_match.group(0).replace(" ", "") if awb_match else None,
            bl=bl_match.group(1) if bl_match else None,
            container=container_match.group(0) if container_match else None,
            invoice=invoice_match.group(1) if invoice_match else None,
        )
