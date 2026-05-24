"""
Dynamic Port Manager for AI Email Organizer
Handles port scanning, conflict detection, and automatic recovery
"""

import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class PortManager:
    DEFAULT_PORT = 4597
    MIN_PORT = 4597
    MAX_PORT = 4600
    SCAN_TIMEOUT = 0.5
    MAX_RETRIES = 3

    def __init__(self, preferred_port: int = None, port_range: Tuple[int, int] = None):
        self.preferred_port = preferred_port or self.DEFAULT_PORT
        self.port_range = port_range or (self.MIN_PORT, self.MAX_PORT)
        self.current_port: Optional[int] = None
        self._lock = threading.Lock()
        self.port_file = self._get_port_file()
        self._initialized = False

    def _get_port_file(self) -> str:
        data_dir = Path(__file__).parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / "port.txt")

    def initialize(self):
        """Initialize port manager"""
        if self._initialized:
            return

        # Try to load saved port
        saved_port = self._load_saved_port()
        if saved_port and self.is_port_available(saved_port):
            self.current_port = saved_port
            logger.info(f"Restored port from file: {saved_port}")

        self._initialized = True

    def _load_saved_port(self) -> Optional[int]:
        try:
            if os.path.exists(self.port_file):
                with open(self.port_file, "r") as f:
                    port_str = f.read().strip()
                    port = int(port_str)
                    if 1024 <= port <= 65535:
                        return port
        except (ValueError, IOError) as e:
            logger.warning(f"Could not load saved port: {e}")
        return None

    def save_port(self, port: int):
        try:
            with open(self.port_file, "w") as f:
                f.write(str(port))
            logger.info(f"Port saved: {port}")
        except IOError as e:
            logger.warning(f"Could not save port: {e}")

    def is_port_available(self, port: int) -> bool:
        """Check if a port is available"""
        if not (1024 <= port <= 65535):
            return False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.SCAN_TIMEOUT)
                result = sock.connect_ex(("127.0.0.1", port))
                return result != 0
        except (socket.error, OSError):
            return False

    def scan_available_ports(self) -> List[int]:
        """Scan port range for available ports"""
        available = []

        for port in range(self.port_range[0], self.port_range[1] + 1):
            if self.is_port_available(port):
                available.append(port)

        return available

    def find_available_port(self) -> Optional[int]:
        """Find an available port"""
        with self._lock:
            # Try saved port first
            saved_port = self._load_saved_port()
            if saved_port and self.is_port_available(saved_port):
                logger.info(f"Using saved port: {saved_port}")
                return saved_port

            # Try preferred port
            if self.is_port_available(self.preferred_port):
                logger.info(f"Preferred port available: {self.preferred_port}")
                return self.preferred_port

            # Scan for available port
            logger.info("Scanning for available ports...")
            available = self.scan_available_ports()

            if available:
                port = available[0]
                logger.info(f"Found available port: {port}")
                return port

            logger.error("No available ports in range")
            return None

    @contextmanager
    def bind_to_port(self, port: int):
        """Context manager for port binding"""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(10)  # 10 second timeout for bind
            sock.bind(("127.0.0.1", port))
            sock.listen(5)
            logger.info(f"Successfully bound to port: {port}")
            yield sock
        except OSError as e:
            logger.error(f"Failed to bind to port {port}: {e}")
            raise
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def start_server(self, app, max_retries: int = None) -> Optional[int]:
        """Find and return available port"""
        max_retries = max_retries or self.MAX_RETRIES

        for attempt in range(max_retries):
            port = self.find_available_port()

            if port is None:
                logger.warning("No ports available, waiting...")
                time.sleep(2)
                continue

            # Test if we can bind
            try:
                with self.bind_to_port(port) as sock:
                    sock.getsockname()

                self.current_port = port
                self.save_port(port)
                return port

            except OSError:
                logger.warning(f"Port {port} became unavailable, retrying...")
                time.sleep(1)
                continue

        logger.error("Failed to find available port after all attempts")
        return None

    def check_port_health(self) -> bool:
        """Check if current port is still available"""
        if self.current_port:
            return self.is_port_available(self.current_port)
        return False

    def recover_from_conflict(self) -> Optional[int]:
        """Attempt to recover from port conflict"""
        logger.info("Attempting port recovery...")

        # Clear saved port
        try:
            if os.path.exists(self.port_file):
                os.remove(self.port_file)
        except Exception:
            pass

        self.current_port = None
        return self.start_server(None, max_retries=2)

    def get_status(self) -> dict:
        """Get port manager status"""
        return {
            "current_port": self.current_port,
            "preferred_port": self.preferred_port,
            "port_range": self.port_range,
            "is_available": self.check_port_health() if self.current_port else False
        }


class ServiceDiscovery:
    """Service discovery for extensions"""

    DISCOVERY_FILE = "service.json"
    LEGACY_FILE = "localhost.json"

    def __init__(self):
        self.data_dir = self._get_data_dir()

    def _get_data_dir(self) -> Path:
        base_path = Path(__file__).parent.parent / "data"
        base_path.mkdir(parents=True, exist_ok=True)
        return base_path

    def write_discovery(self, port: int, host: str = "127.0.0.1"):
        """Write service discovery file"""
        discovery = {
            "service": "AI Email Organizer",
            "version": "9.7.0",
            "host": host,
            "port": port,
            "api_base": f"http://{host}:{port}",
            "endpoints": {
                "health": f"http://{host}:{port}/api/v1/health",
                "classify": f"http://{host}:{port}/api/v1/classify",
                "categories": f"http://{host}:{port}/api/v1/categories",
                "feedback": f"http://{host}:{port}/api/v1/feedback",
                "discover": f"http://{host}:{port}/api/v1/extension/discover"
            },
            "timestamp": int(time.time()),
            "ttl": 300
        }

        discovery_path = self.data_dir / self.DISCOVERY_FILE
        with open(discovery_path, "w") as f:
            json.dump(discovery, f, indent=2)

        # Legacy file for older extensions
        legacy_path = self.data_dir / self.LEGACY_FILE
        with open(legacy_path, "w") as f:
            json.dump(discovery, f, indent=2)

        return discovery

    def read_discovery(self) -> Optional[dict]:
        """Read service discovery file"""
        import json

        discovery_path = self.data_dir / self.DISCOVERY_FILE

        if not discovery_path.exists():
            return None

        try:
            with open(discovery_path, "r") as f:
                data = json.load(f)

            # Check TTL
            if "timestamp" in data:
                age = time.time() - data["timestamp"]
                if age > data.get("ttl", 300):
                    return None

            return data
        except (json.JSONDecodeError, IOError):
            return None

    def find_service(self) -> Optional[dict]:
        """Find running service"""
        discovery = self.read_discovery()
        if discovery:
            return discovery

        # Try to find service by probing ports
        ports_to_try = list(range(4597, 4509, -1))

        for port in ports_to_try:
            if self._test_port(port):
                return self.write_discovery(port)

        return None

    def _test_port(self, port: int) -> bool:
        """Test if port has service"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False


# Global instances
port_manager = PortManager()
discovery = ServiceDiscovery()


def initialize_port() -> int:
    """Initialize port and return active port"""
    try:
        port_manager.initialize()
        port = port_manager.find_available_port()

        if port:
            discovery.write_discovery(port)
            return port
        else:
            logger.error("Could not find available port")
            return 4597  # Fallback

    except Exception as e:
        logger.error(f"Port initialization error: {e}")
        return 4597


def get_service_info() -> dict:
    """Get service info for discovery"""
    info = discovery.find_service()
    if info:
        return info

    return {
        "host": "127.0.0.1",
        "port": port_manager.current_port or 4597,
        "version": "9.7.0"
    }
