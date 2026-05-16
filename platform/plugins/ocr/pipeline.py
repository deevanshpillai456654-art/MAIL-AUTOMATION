from __future__ import annotations
import hashlib
from sdk.models import DocumentRecord, RiskLevel, SearchRecord
from plugins.ocr.classification.classifier import DocumentClassifier
from plugins.ocr.extraction.extractor import FieldExtractor
from plugins.ocr.validation.validator import DocumentValidator
from plugins.ocr.review.review_queue import OCRReviewQueue
from plugins.ocr.indexing.index import OCRSearchIndex

class OCRPipeline:
    def __init__(self) -> None:
        self.classifier = DocumentClassifier()
        self.extractor = FieldExtractor()
        self.validator = DocumentValidator()
        self.review = OCRReviewQueue()
        self.index = OCRSearchIndex()

    def analyze_text(self, tenant_id: str, filename: str, text: str) -> dict:
        checksum = hashlib.sha256((text or "").encode()).hexdigest()
        classified = self.classifier.classify(text)
        fields = self.extractor.extract(text)
        missing = self.validator.missing_fields(classified["document_type"], fields)
        document = DocumentRecord(
            document_id=checksum[:16], tenant_id=tenant_id, filename=filename,
            document_type=classified["document_type"], risk_level=RiskLevel.MEDIUM,
            confidence=float(classified["confidence"]), extracted_fields=fields, checksum=checksum
        )
        review_required = self.review.maybe_enqueue(document)
        tokens = [token for values in fields.values() for token in values]
        self.index.add(SearchRecord(record_id=document.document_id, tenant_id=tenant_id, entity_type="document", entity_id=document.document_id, text=text, tokens=tokens, metadata={"filename": filename}))
        return {"document": document.__dict__, "missing_fields": missing, "review_required": review_required}
