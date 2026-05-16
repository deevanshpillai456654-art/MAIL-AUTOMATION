from __future__ import annotations
from typing import Dict

class DocumentClassifier:
    KEYWORDS = {
        "invoice": ["invoice", "tax invoice", "gstin"],
        "packing_list": ["packing list", "packages", "net weight", "gross weight"],
        "bill_of_lading": ["bill of lading", "shipper", "consignee", "vessel"],
        "airway_bill": ["air waybill", "awb", "airline"],
        "pod": ["proof of delivery", "delivered", "received by"],
        "shipping_bill": ["shipping bill", "let export order"],
        "bill_of_entry": ["bill of entry", "customs", "duty"],
    }

    def classify(self, text: str) -> Dict[str, object]:
        hay = (text or "").lower()
        scores = {doc: sum(1 for kw in kws if kw in hay) for doc, kws in self.KEYWORDS.items()}
        best = max(scores, key=scores.get) if scores else "unknown"
        confidence = min(1.0, scores.get(best, 0) / 3.0)
        return {"document_type": best if scores.get(best, 0) else "unknown", "confidence": confidence, "scores": scores}
