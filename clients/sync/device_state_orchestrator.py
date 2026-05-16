"""Device state registry for cross-platform clients."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable

@dataclass
class DeviceState:
    tenant_id: str
    account_id: str
    device_id: str
    platform: str
    status: str = "active"
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class DeviceStateOrchestrator:
    def __init__(self):
        self._devices: Dict[str, DeviceState] = {}

    def register(self, tenant_id: str, account_id: str, device_id: str, platform: str) -> DeviceState:
        key = self._key(tenant_id, account_id, device_id)
        state = DeviceState(str(tenant_id), str(account_id), str(device_id), str(platform))
        self._devices[key] = state
        return state

    def heartbeat(self, tenant_id: str, account_id: str, device_id: str) -> bool:
        key = self._key(tenant_id, account_id, device_id)
        if key not in self._devices:
            return False
        self._devices[key].last_seen = datetime.now(timezone.utc).isoformat()
        return True

    def devices_for_account(self, tenant_id: str, account_id: str) -> Iterable[DeviceState]:
        prefix = f"{tenant_id}:{account_id}:"
        return [device for key, device in self._devices.items() if key.startswith(prefix)]

    @staticmethod
    def _key(tenant_id: str, account_id: str, device_id: str) -> str:
        return f"{tenant_id}:{account_id}:{device_id}"
