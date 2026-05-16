from __future__ import annotations
from typing import Dict, List
from sdk.models import SearchRecord

class OCRSearchIndex:
    def __init__(self) -> None:
        self.records: Dict[str, SearchRecord] = {}

    def add(self, record: SearchRecord) -> None:
        self.records[record.record_id] = record

    def query(self, tenant_id: str, text: str) -> List[SearchRecord]:
        q = text.lower()
        return [r for r in self.records.values() if r.tenant_id == tenant_id and q in r.text.lower()]
