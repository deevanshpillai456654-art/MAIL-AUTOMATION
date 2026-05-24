"""
Port management API endpoints
"""


import os
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth_or_localhost
from backend.utils.port_manager import PortManager, get_service_info

router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])

port_manager = PortManager()


class PortConfig(BaseModel):
    preferred_port: Optional[int] = 4597
    port_range_min: Optional[int] = 4597
    port_range_max: Optional[int] = 4610


class PortResponse(BaseModel):
    current_port: int
    available_ports: list
    port_range: tuple
    status: str


@router.get("/port/status")
async def get_port_status():
    info = get_service_info()

    return {
        "host": info.get("host", "127.0.0.1"),
        "port": info.get("port", 4597),
        "version": info.get("version", "9.7.0"),
        "is_available": port_manager.check_port_health()
    }


@router.post("/port/scan")
async def scan_ports(config: PortConfig = None):
    if config:
        port_manager.port_range = (config.port_range_min, config.port_range_max)

    available = port_manager.scan_available_ports()

    return {
        "available_ports": available,
        "count": len(available),
        "port_range": port_manager.port_range
    }


@router.post("/port/recover")
async def recover_port():
    new_port = port_manager.recover_from_conflict()

    if new_port:
        return {
            "status": "success",
            "new_port": new_port,
            "message": f"Service recovered on port {new_port}"
        }

    raise HTTPException(status_code=500, detail="Failed to recover port")


@router.get("/port/config")
async def get_port_config():
    return {
        "preferred_port": port_manager.preferred_port,
        "port_range": port_manager.port_range,
        "current_port": port_manager.current_port or port_manager.DEFAULT_PORT
    }


@router.post("/port/config")
async def set_port_config(config: PortConfig):
    port_manager.preferred_port = config.preferred_port or 4597
    port_manager.port_range = (config.port_range_min or 4597, config.port_range_max or 4610)

    return {
        "status": "success",
        "preferred_port": port_manager.preferred_port,
        "port_range": port_manager.port_range
    }


@router.get("/system/resources")
async def get_system_resources():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
        disk = psutil.disk_usage(_disk_root)

        return {
            "cpu": {
                "percent": cpu,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
