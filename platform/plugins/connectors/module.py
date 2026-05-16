from __future__ import annotations
from typing import Dict
from sdk.connector import RESTConnector, WebhookConnector, CSVConnector, EmailConnector

class ConnectorCatalog:
    def __init__(self):
        self.catalog: Dict[str, dict] = {
            "tally": {"category": "erp", "syncs": ["customers", "invoice_references", "outstanding", "gst_details", "payment_status"]},
            "busy": {"category": "erp", "syncs": ["customers", "invoice_references", "outstanding", "gst_details", "payment_status"]},
            "zoho_books": {"category": "erp", "syncs": ["customers", "invoice_references", "outstanding", "gst_details", "payment_status"]},
            "erpnext": {"category": "erp", "syncs": ["customers", "invoice_references", "outstanding", "gst_details", "payment_status"]},
            "marg_erp": {"category": "erp", "syncs": ["customers", "invoice_references", "outstanding", "gst_details", "payment_status"]},
            "zoho_crm": {"category": "crm", "syncs": ["leads", "contacts", "activities", "followups", "notes"]},
            "hubspot": {"category": "crm", "syncs": ["leads", "contacts", "activities", "followups", "notes"]},
            "salesforce": {"category": "crm", "syncs": ["leads", "contacts", "activities", "followups", "notes"]},
            "freshsales": {"category": "crm", "syncs": ["leads", "contacts", "activities", "followups", "notes"]},
            "generic_tracking_api": {"category": "tracking", "connector_class": "RESTConnector"},
            "generic_tracking_webhook": {"category": "tracking", "connector_class": "WebhookConnector"},
            "generic_tracking_csv": {"category": "tracking", "connector_class": "CSVConnector"},
            "generic_tracking_email": {"category": "tracking", "connector_class": "EmailConnector"},
        }

    def list(self):
        return self.catalog

def create_plugin():
    return ConnectorCatalog()
