from __future__ import annotations
from typing import Dict, List
from sdk.models import DocumentRecord

class OCRReviewQueue:
    def __init__(self, threshold: float = 0.75) -> None:
        self.threshold = threshold
        self.items: Dict[str, DocumentRecord] = {}

    def maybe_enqueue(self, document: DocumentRecord) -> bool:
        if document.confidence < self.threshold:
            self.items[document.document_id] = document
            return True
        return False

    def list_pending(self, tenant_id: str) -> List[DocumentRecord]:
        return [doc for doc in self.items.values() if doc.tenant_id == tenant_id]
