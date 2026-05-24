"""
Model Cache - AI Model Caching
=================================

Model caching for efficient inference:
- Model loading/unloading
- Memory management
- Version tracking
- Hot swapping
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("model.cache")


@dataclass
class ModelInfo:
    """Model information"""
    model_id: str
    model_type: str
    version: str
    loaded_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    use_count: int = 0
    memory_mb: float = 0.0


class ModelCache:
    """
    AI Model cache manager.
    """

    def __init__(self, max_memory_mb: float = 2048.0):
        self.max_memory_mb = max_memory_mb
        self._models: Dict[str, Any] = {}
        self._model_info: Dict[str, ModelInfo] = {}
        self._current_memory = 0.0

        logger.info(f"ModelCache initialized (max: {max_memory_mb}MB)")

    def register(self, model_id: str, model_type: str, version: str, model: Any, memory_mb: float):
        """Register a model"""
        info = ModelInfo(
            model_id=model_id,
            model_type=model_type,
            version=version,
            memory_mb=memory_mb
        )

        self._models[model_id] = model
        self._model_info[model_id] = info
        self._current_memory += memory_mb

        logger.info(f"Model registered: {model_id} ({memory_mb}MB)")

    def get(self, model_id: str) -> Optional[Any]:
        """Get a model"""
        if model_id not in self._models:
            return None

        info = self._model_info[model_id]
        info.last_used = time.time()
        info.use_count += 1

        return self._models[model_id]

    def unload(self, model_id: str):
        """Unload a model"""
        if model_id in self._models:
            info = self._model_info[model_id]
            self._current_memory -= info.memory_mb

            del self._models[model_id]
            del self._model_info[model_id]

            logger.info(f"Model unloaded: {model_id}")

    def evict_lru(self):
        """Evict least recently used model"""
        if not self._models:
            return

        # Find oldest
        oldest_id = None
        oldest_time = float('inf')

        for model_id, info in self._model_info.items():
            if info.last_used < oldest_time:
                oldest_time = info.last_used
                oldest_id = model_id

        if oldest_id:
            self.unload(oldest_id)

    def can_load(self, memory_mb: float) -> bool:
        """Check if model can be loaded"""
        if self._current_memory + memory_mb > self.max_memory_mb:
            # Try to free space
            while self._current_memory + memory_mb > self.max_memory_mb and self._models:
                self.evict_lru()

            return self._current_memory + memory_mb <= self.max_memory_mb

        return True

    def get_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "models_loaded": len(self._models),
            "memory_used_mb": self._current_memory,
            "memory_max_mb": self.max_memory_mb,
            "memory_percent": (self._current_memory / self.max_memory_mb) * 100
        }


# Global model cache
_model_cache: Optional[ModelCache] = None


def get_model_cache() -> ModelCache:
    """Get global model cache"""
    global _model_cache
    if _model_cache is None:
        _model_cache = ModelCache()
    return _model_cache


__all__ = ["ModelCache", "ModelInfo", "get_model_cache"]
