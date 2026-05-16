from pathlib import Path
import sys
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from plugins.ocr.pipeline import OCRPipeline
from plugins.search.indexer import OperationalSearchIndex


def test_ocr_pipeline_classifies_extracts_and_indexes():
    text = 'Tax Invoice INV-100 GSTIN 27ABCDE1234F1Z5 Container ABCD1234567 HS 996511'
    result = OCRPipeline().analyze_text('t1', 'invoice.pdf', text)
    assert result['document']['document_type'] == 'invoice'
    assert result['document']['extracted_fields']['gstin'] == ['27ABCDE1234F1Z5']


def test_search_index_finds_operational_refs():
    idx = OperationalSearchIndex()
    idx.index('t1', 'shipment', 'S1', 'AWB 123-12345678 BL ABC777 customer Mumbai')
    found = idx.search('t1', 'ABC777')
    assert len(found) == 1
