from __future__ import annotations
import re
from typing import Dict

PATTERNS = {
    "gstin": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "awb": re.compile(r"\b\d{3}[- ]?\d{8}\b"),
    "container": re.compile(r"\b[A-Z]{4}\d{7}\b"),
    "hs_code": re.compile(r"\b\d{4}(?:\d{2})?(?:\d{2})?\b"),
    "invoice_ref": re.compile(r"\b(?:INVOICE|INV)[:#\s-]*([A-Z0-9/-]{4,30})\b", re.I),
}

class FieldExtractor:
    def extract(self, text: str) -> Dict[str, list[str]]:
        return {name: sorted(set(match.group(0) for match in pattern.finditer(text or ""))) for name, pattern in PATTERNS.items()}
