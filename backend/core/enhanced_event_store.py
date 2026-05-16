"""
Enhanced Event Store - Wrapper
===============================

Extended event store with enhanced features.
"""

from .event_store import DurableEventStore, get_event_store as _get_event_store

class EnhancedEventStore(DurableEventStore):
    """Enhanced event store"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def get_stats_extended(self) -> dict:
        """Extended statistics"""
        stats = self.get_stats()
        return {
            **stats,
            "version": "2.0.0",
            "features": ["replay", "idempotency", "snapshots"]
        }


def get_event_store() -> EnhancedEventStore:
    """Get enhanced event store"""
    return _get_event_store()


__all__ = ["EnhancedEventStore", "get_event_store"]