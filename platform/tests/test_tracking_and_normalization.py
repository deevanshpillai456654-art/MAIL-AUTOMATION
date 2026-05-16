from pathlib import Path
import sys
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from sdk.models import TenantContext
from plugins.tracking.connectors import TrackingCSVConnector
from plugins.tracking.aggregation import TrackingAggregationEngine


def test_tracking_ingestion_normalizes_and_dedupes():
    ctx = TenantContext(tenant_id='t1')
    connector = TrackingCSVConnector()
    result = connector.parse_rows(ctx, [
        {'shipment_key':'S1','status':'ARRIVED_AT_PORT','timestamp':'2026-05-15T10:00:00Z','mode':'sea'},
        {'shipment_key':'S1','status':'PORT_ENTRY_COMPLETE','timestamp':'2026-05-15T10:05:00Z','mode':'sea'},
        {'shipment_key':'S1','status':'ARRIVED_AT_PORT','timestamp':'2026-05-15T10:00:00Z','mode':'sea'},
    ])
    engine = TrackingAggregationEngine()
    stats = engine.ingest(result.events)
    assert stats['received'] == 3
    assert stats['added'] == 2
    timeline = engine.timeline('t1', 'S1')
    assert timeline[0]['normalized_status'] == 'ARRIVED_PORT'
