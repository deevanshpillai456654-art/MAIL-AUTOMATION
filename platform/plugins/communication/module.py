from plugins.communication.timeline import UnifiedCommunicationTimeline
from plugins.communication.linking import CommunicationLinker

class CommunicationPlugin:
    def __init__(self):
        self.timeline = UnifiedCommunicationTimeline()
        self.linker = CommunicationLinker()

def create_plugin():
    return CommunicationPlugin()
