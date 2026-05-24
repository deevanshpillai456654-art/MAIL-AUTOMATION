"""
Service Discovery for Browser Extensions
Allows Gmail extension and Outlook add-in to discover the local service
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.runtime_version import APP_VERSION, DISPLAY_VERSION

router = APIRouter()


class ServiceDiscovery:
    DISCOVERY_FILE = "service.json"
    LEGACY_FILE = "localhost.json"

    def __init__(self):
        self.data_dir = self._get_data_dir()

    def _get_data_dir(self) -> Path:
        base_path = Path(__file__).parent.parent / "data"
        base_path.mkdir(parents=True, exist_ok=True)
        return base_path

    def write_discovery(self, port: int, host: str = "127.0.0.1"):
        discovery = {
            "service": DISPLAY_VERSION,
            "version": APP_VERSION,
            "host": host,
            "port": port,
            "api_base": f"http://{host}:{port}",
            "endpoints": {
                "health": f"http://{host}:{port}/api/v1/health",
                "classify": f"http://{host}:{port}/api/v1/classify",
                "categories": f"http://{host}:{port}/api/v1/categories",
                "feedback": f"http://{host}:{port}/api/v1/feedback"
            },
            "timestamp": int(time.time()),
            "ttl": 300
        }

        discovery_path = self.data_dir / self.DISCOVERY_FILE
        with open(discovery_path, "w") as f:
            json.dump(discovery, f, indent=2)

        legacy_path = self.data_dir / self.LEGACY_FILE
        with open(legacy_path, "w") as f:
            json.dump(discovery, f, indent=2)

        return discovery

    def read_discovery(self) -> Optional[Dict]:
        discovery_path = self.data_dir / self.DISCOVERY_FILE

        if not discovery_path.exists():
            return None

        try:
            with open(discovery_path, "r") as f:
                data = json.load(f)

            if "timestamp" in data:
                age = time.time() - data["timestamp"]
                if age > data.get("ttl", 300):
                    return None

            return data
        except Exception:
            return None

    def find_service(self) -> Optional[Dict]:
        discovery = self.read_discovery()
        if discovery:
            return discovery

        ports_to_try = [4597, 4501, 4502, 4503, 4504, 4505]

        for port in ports_to_try:
            if self._test_port(port):
                return self.write_discovery(port)

        return None

    def _test_port(self, port: int) -> bool:
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False


discovery = ServiceDiscovery()


@router.get("/discovery/service")
async def get_service_info():
    info = discovery.find_service()
    if info:
        return info
    raise HTTPException(status_code=404, detail="Service not found")


@router.get("/discovery/health")
async def check_service_health():
    info = discovery.find_service()
    if not info:
        return {"status": "not_found", "available": False}

    import requests
    try:
        response = requests.get(info["endpoints"]["health"], timeout=2)
        return {
            "status": "healthy" if response.ok else "unhealthy",
            "available": True,
            "port": info["port"]
        }
    except Exception:
        return {"status": "unreachable", "available": False, "port": info["port"]}


@router.post("/discovery/scan")
async def scan_for_service():
    info = discovery.find_service()

    if info:
        return {
            "found": True,
            "host": info["host"],
            "port": info["port"],
            "version": info.get("version", "unknown")
        }

    return {"found": False, "message": "Service not running"}


@router.get("/discovery/endpoints")
async def get_endpoints():
    info = discovery.find_service()
    if not info:
        raise HTTPException(status_code=404, detail="Service not found")

    return info.get("endpoints", {})


def get_known_ports() -> List[int]:
    return list(range(4597, 4509, -1))


def is_service_running(port: int = 4597) -> bool:
    return discovery._test_port(port)
