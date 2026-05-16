from plugins.whatsapp_ops.session_manager import LocalWhatsAppSessionManager
from plugins.whatsapp_ops.local_queue import LocalWhatsAppQueue, WhatsAppSendItem
from plugins.whatsapp_ops.detector import WhatsAppReferenceDetector
from plugins.whatsapp_ops.templates import OperationalTemplateService

class WhatsAppOperationsEngine:
    def __init__(self) -> None:
        self.sessions = LocalWhatsAppSessionManager()
        self.queue = LocalWhatsAppQueue()
        self.detector = WhatsAppReferenceDetector()
        self.templates = OperationalTemplateService()

def create_plugin():
    return WhatsAppOperationsEngine()
