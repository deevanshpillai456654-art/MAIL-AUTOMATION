"""Adaptive buffering for realtime event delivery."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BufferDecision:
    batch_size: int
    flush_interval_ms: int
    reason: str


class AdaptiveBuffering:
    def __init__(self, min_batch: int = 10, max_batch: int = 500):
        self.min_batch = min_batch
        self.max_batch = max_batch
        self._latency_ms = 0.0

    def observe_latency(self, latency_ms: float) -> None:
        self._latency_ms = (self._latency_ms * 0.8) + (max(0.0, latency_ms) * 0.2)

    def decide(self, queue_depth: int, pressure_ratio: float = 0.0) -> BufferDecision:
        if pressure_ratio > 0.8 or self._latency_ms > 1500:
            return BufferDecision(batch_size=self.min_batch, flush_interval_ms=100, reason="high_pressure")
        if queue_depth > 1000:
            return BufferDecision(batch_size=self.max_batch, flush_interval_ms=500, reason="bulk_drain")
        return BufferDecision(batch_size=min(self.max_batch, max(self.min_batch, queue_depth or self.min_batch)), flush_interval_ms=250, reason="balanced")


__all__ = ["BufferDecision", "AdaptiveBuffering"]
