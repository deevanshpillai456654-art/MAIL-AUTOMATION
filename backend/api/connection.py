"""
Connection and Discovery API endpoints for extensions
"""


import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.runtime_version import APP_VERSION
from backend.utils.connection import (
    connection_validator,
    create_extension_token,
    get_connection_stats,
    handshake,
    validate_extension_connection,
)
from backend.utils.discovery import discovery, get_known_ports

router = APIRouter()


class HandshakeRequest(BaseModel):
    client_id: str
    client_type: str
    version: str
    timestamp: int
    signature: Optional[str] = None


class HandshakeResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    api_base: Optional[str] = None
    message: Optional[str] = None


class ConnectionCheck(BaseModel):
    token: str
    client_id: Optional[str] = None


@router.post("/extension/handshake")
async def extension_handshake(request: HandshakeRequest):
    if request.signature and not handshake.verify_handshake(request.client_id, request.timestamp, request.signature):
        raise HTTPException(status_code=401, detail="Invalid handshake")

    token = create_extension_token(request.client_id)
    info = discovery.find_service()

    return HandshakeResponse(
        success=True,
        token=token,
        api_base=info["api_base"] if info else None,
        message="Handshake successful"
    )


@router.post("/extension/connect")
async def extension_connect(check: ConnectionCheck):
    is_valid = validate_extension_connection(check.token, check.client_id)

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "status": "connected",
        "client_id": check.client_id,
        "timestamp": int(time.time())
    }


@router.post("/extension/disconnect")
async def extension_disconnect(token: str):
    connection_validator.revoke_token(token)
    return {"status": "disconnected"}


@router.get("/extension/status")
async def extension_status():
    info = discovery.find_service()

    return {
        "service_available": info is not None,
        "service_port": info["port"] if info else None,
        "connection_stats": get_connection_stats()
    }


@router.get("/extension/ports")
async def available_ports():
    from backend.utils.connection import PortScanner
    scan_results = PortScanner.scan_ports()
    available = [port for port, is_used in scan_results.items() if not is_used]

    return {
        "scanned_ports": PortScanner.SAFE_PORTS,
        "available_ports": available,
        "default_port": 4597
    }


@router.get("/extension/discover")
async def discover_service():
    info = discovery.find_service()

    if info:
        return {
            "found": True,
            "service": "AI Email Organizer",
            "host": info["host"],
            "port": info["port"],
            "api_base": info["api_base"],
            "version": info.get("version", APP_VERSION)
        }

    return {
        "found": False,
        "message": "Service not running. Start the local service.",
        "suggested_ports": get_known_ports()
    }


@router.post("/extension/heartbeat")
async def extension_heartbeat(
    token: str = Header(...),
    client_id: Optional[str] = Header(None)
):
    is_valid = validate_extension_connection(token, client_id)

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid token")

    return {
        "status": "alive",
        "timestamp": int(time.time())
    }
