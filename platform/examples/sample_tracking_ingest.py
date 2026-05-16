from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdk.models import TenantContext
from plugins.tracking.connectors import TrackingCSVConnector
from plugins.tracking.aggregation import TrackingAggregationEngine

ctx = TenantContext(tenant_id='demo')
connector = TrackingCSVConnector()
result = connector.parse_rows(ctx, [{'shipment_key': 'SHIP-1', 'status': 'ARRIVED_AT_PORT', 'timestamp': '2026-05-15T10:00:00Z'}])
engine = TrackingAggregationEngine()
print(engine.ingest(result.events))
print(engine.timeline('demo', 'SHIP-1'))
