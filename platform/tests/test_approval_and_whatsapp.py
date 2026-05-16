from pathlib import Path
import sys
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from sdk.models import TenantContext
from plugins.approvals.policy import AutomationPolicyEngine
from plugins.whatsapp_ops.detector import WhatsAppReferenceDetector


def test_high_risk_document_requires_approval_by_default():
    ctx = TenantContext(tenant_id='t1')
    engine = AutomationPolicyEngine()
    result = engine.evaluate(ctx, workflow_type='document_send', document_type='invoice', customer_id='c1')
    assert result['decision'] == 'approval_required'
    assert result['risk'] == 'high'


def test_whatsapp_reference_detection():
    refs = WhatsAppReferenceDetector().detect('Please check AWB 123-12345678 and container ABCD1234567 invoice INV-55')
    assert refs.awb == '123-12345678'
    assert refs.container == 'ABCD1234567'
    assert refs.invoice == 'INV-55'
