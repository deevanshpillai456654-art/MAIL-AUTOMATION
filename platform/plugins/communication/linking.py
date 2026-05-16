from __future__ import annotations
from sdk.models import CommunicationMessage, ShipmentReference
from plugins.whatsapp_ops.detector import WhatsAppReferenceDetector

class CommunicationLinker:
    def __init__(self) -> None:
        self.detector = WhatsAppReferenceDetector()

    def auto_link(self, message: CommunicationMessage) -> CommunicationMessage:
        refs = self.detector.detect(message.body)
        message.shipment_refs = ShipmentReference(
            shipment_id=message.shipment_refs.shipment_id,
            awb=message.shipment_refs.awb or refs.awb,
            bl=message.shipment_refs.bl or refs.bl,
            container=message.shipment_refs.container or refs.container,
            invoice=message.shipment_refs.invoice or refs.invoice,
            customer_id=message.shipment_refs.customer_id,
        )
        return message
