from __future__ import annotations
import re
from typing import Dict, List
from sdk.models import SearchRecord

TOKEN_RE = re.compile(r"[A-Za-z0-9/-]{2,}")

class OperationalSearchIndex:
    def __init__(self) -> None:
        self.records: Dict[str, SearchRecord] = {}

    def tokenize(self, text: str) -> List[str]:
        return [t.lower() for t in TOKEN_RE.findall(text or "")]

    def index(self, tenant_id: str, entity_type: str, entity_id: str, text: str, metadata: dict | None = None) -> SearchRecord:
        record_id = f"{tenant_id}:{entity_type}:{entity_id}"
        record = SearchRecord(record_id=record_id, tenant_id=tenant_id, entity_type=entity_type, entity_id=entity_id, text=text, tokens=self.tokenize(text), metadata=metadata or {})
        self.records[record_id] = record
        return record

    def search(self, tenant_id: str, query: str, limit: int = 20) -> List[SearchRecord]:
        tokens = set(self.tokenize(query))
        scored = []
        for record in self.records.values():
            if record.tenant_id != tenant_id:
                continue
            score = len(tokens & set(record.tokens))
            if score:
                scored.append((score, record))
        return [r for _, r in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]
