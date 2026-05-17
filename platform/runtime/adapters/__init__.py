"""Runtime adapter layer — bridges plugins to platform infrastructure."""
from .db_adapter import DBAdapter
from .queue_adapter import QueueAdapter
from .webhook_adapter import WebhookAdapter

__all__ = ["DBAdapter", "QueueAdapter", "WebhookAdapter"]
