from __future__ import annotations
from typing import Dict, List

class DocumentValidator:
    REQUIRED_BY_TYPE = {
        "invoice": ["gstin", "invoice_ref"],
        "airway_bill": ["awb"],
        "packing_list": [],
        "bill_of_lading": ["container"],
    }

    def missing_fields(self, document_type: str, fields: Dict[str, list[str]]) -> List[str]:
        return [field for field in self.REQUIRED_BY_TYPE.get(document_type, []) if not fields.get(field)]

    def compare(self, left: Dict[str, list[str]], right: Dict[str, list[str]]) -> Dict[str, object]:
        mismatches = []
        for key in sorted(set(left) | set(right)):
            if left.get(key) and right.get(key) and set(left[key]) != set(right[key]):
                mismatches.append(key)
        return {"mismatch_count": len(mismatches), "mismatches": mismatches}
