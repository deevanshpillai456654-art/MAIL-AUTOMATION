"""
Streaming Pipeline
==================

Streaming pipeline wrapper.
"""

from .streaming import StreamingPipeline
from .streaming import get_streaming_pipeline as _get_pipeline


class StreamingPipeline(StreamingPipeline):
    """Enhanced streaming pipeline"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


def get_streaming_pipeline() -> StreamingPipeline:
    """Get streaming pipeline"""
    return _get_pipeline()


__all__ = ["StreamingPipeline", "get_streaming_pipeline"]
