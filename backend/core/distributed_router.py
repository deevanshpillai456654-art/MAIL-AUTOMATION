"""Tenant and mailbox aware routing helpers."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class RouteKey:
    tenant_id: str
    account_id: str
    resource: str = "mailbox"

    def validate(self) -> None:
        if not self.tenant_id or not self.account_id:
            raise ValueError("tenant_id and account_id are required for isolated routing")


@dataclass(frozen=True)
class RouteDecision:
    shard_id: int
    namespace: str
    candidates: List[str]


class DistributedRouter:
    def __init__(self, shard_count: int = 64):
        self.shard_count = max(1, shard_count)

    def route(self, key: RouteKey, nodes: List[str] | None = None) -> RouteDecision:
        key.validate()
        nodes = sorted(nodes or ["local-node"])
        raw = f"{key.tenant_id}:{key.account_id}:{key.resource}"
        shard = int(hashlib.sha256(raw.encode("utf-8")).hexdigest(), 16) % self.shard_count
        preferred = nodes[shard % len(nodes)]
        return RouteDecision(shard_id=shard, namespace=raw, candidates=[preferred] + [node for node in nodes if node != preferred])


__all__ = ["RouteKey", "RouteDecision", "DistributedRouter"]
