"""
Storage Abstraction Layer
=========================

Storage abstraction wrapper.
"""

try:
    # Prefer the richer implementation when the local_service package is present.
    from .local_service.storage.storage_abstraction import StorageAbstractionLayer
except ImportError:
    # Fallback to basic implementation when local_service is unavailable.
    class StorageAbstractionLayer:
        """Storage abstraction layer"""
        def __init__(self):
            pass

        def get_stats(self) -> dict:
            return {"status": "available"}


def get_storage_layer() -> StorageAbstractionLayer:
    """Get storage layer"""
    return StorageAbstractionLayer()


__all__ = ["StorageAbstractionLayer", "get_storage_layer"]
