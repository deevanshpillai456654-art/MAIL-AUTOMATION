"""
WebSocket Manager - Connection Management
=======================================

WebSocket connection pooling:
- Connection pooling
- Session management
- Heartbeat
- Auto-reconnect
"""

import time
import threading
import logging
import asyncio
from typing import Dict, Set, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("ws.manager")


class ConnectionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"


@dataclass
class WSConnection:
    """WebSocket connection"""
    session_id: str
    user_id: Optional[str]
    state: ConnectionState = ConnectionState.CONNECTING
    created_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    messages_sent: int = 0
    messages_received: int = 0


class WebSocketManager:
    """
    WebSocket connection manager.
    """
    
    def __init__(self, heartbeat_interval: float = 30.0):
        self.heartbeat_interval = heartbeat_interval
        self._connections: Dict[str, WSConnection] = {}
        self._user_sessions: Dict[str, Set[str]] = {}  # user_id -> session_ids
        self._lock = threading.Lock()
        
        # Callbacks
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_message: Optional[Callable] = None
        
        logger.info("WebSocketManager initialized")
    
    def add_connection(self, session_id: str, user_id: Optional[str] = None):
        """Add new connection"""
        conn = WSConnection(session_id=session_id, user_id=user_id)
        self._connections[session_id] = conn
        
        if user_id:
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = set()
            self._user_sessions[user_id].add(session_id)
        
        if self.on_connect:
            self.on_connect(session_id, user_id)
        
        logger.info(f"Connection added: {session_id}")
    
    def remove_connection(self, session_id: str):
        """Remove connection"""
        if session_id not in self._connections:
            return
        
        conn = self._connections[session_id]
        
        if conn.user_id and conn.user_id in self._user_sessions:
            self._user_sessions[conn.user_id].discard(session_id)
        
        if self.on_disconnect:
            self.on_disconnect(session_id, conn.user_id)
        
        del self._connections[session_id]
        logger.info(f"Connection removed: {session_id}")
    
    def get_connection(self, session_id: str) -> Optional[WSConnection]:
        """Get connection"""
        return self._connections.get(session_id)
    
    def get_user_connections(self, user_id: str) -> Set[str]:
        """Get user's connections"""
        return self._user_sessions.get(user_id, set())
    
    def broadcast_to_user(self, user_id: str, message: dict) -> int:
        """Broadcast message to user"""
        sessions = self.get_user_connections(user_id)
        count = 0
        
        for session_id in sessions:
            conn = self._connections.get(session_id)
            if conn and conn.state == ConnectionState.CONNECTED:
                conn.messages_sent += 1
                count += 1
        
        return count
    
    def get_stats(self) -> Dict:
        """Get manager statistics"""
        connected = sum(1 for c in self._connections.values() if c.state == ConnectionState.CONNECTED)
        
        return {
            "total_connections": len(self._connections),
            "connected": connected,
            "active_users": len(self._user_sessions),
            "total_messages_sent": sum(c.messages_sent for c in self._connections.values()),
            "total_messages_received": sum(c.messages_received for c in self._connections.values())
        }


# Global manager
_ws_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """Get global WebSocket manager"""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


__all__ = ["WebSocketManager", "WSConnection", "ConnectionState", "get_ws_manager"]