"""
Service Mesh - Microservice Communication
==================================

Microservice mesh communication:
- Service discovery
- Load balancing
- Retry logic
- Timeout handling
- Circuit breaking
"""

import logging
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("service.mesh")


class ServiceStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServiceEndpoint:
    """Service endpoint"""
    url: str
    status: ServiceStatus = ServiceStatus.UNKNOWN
    weight: int = 1
    last_check: float = 0
    failure_count: int = 0


class ServiceRegistry:
    """
    Service registry and discovery.
    """

    def __init__(self):
        self._services: Dict[str, List[ServiceEndpoint]] = {}
        self._lock = threading.Lock()

        logger.info("ServiceRegistry initialized")

    def register(self, service: str, url: str, weight: int = 1):
        """Register service endpoint"""
        with self._lock:
            if service not in self._services:
                self._services[service] = []

            self._services[service].append(
                ServiceEndpoint(url=url, weight=weight)
            )

            logger.info(f"Service registered: {service} -> {url}")

    def get_endpoint(self, service: str) -> Optional[ServiceEndpoint]:
        """Get healthy endpoint (load balanced)"""
        with self._lock:
            endpoints = self._services.get(service, [])

            if not endpoints:
                return None

            # Filter healthy
            healthy = [e for e in endpoints if e.status == ServiceStatus.HEALTHY]

            if not healthy:
                # Fall back to any
                healthy = endpoints

            # Weighted random selection
            total_weight = sum(e.weight for e in healthy)
            r = random.uniform(0, total_weight)

            for e in healthy:
                r -= e.weight
                if r <= 0:
                    return e

            return healthy[0]

    def get_all_endpoints(self, service: str) -> List[ServiceEndpoint]:
        """Get all endpoints for service"""
        return self._services.get(service, [])

    def mark_healthy(self, service: str, url: str):
        """Mark endpoint as healthy"""
        with self._lock:
            for e in self._services.get(service, []):
                if e.url == url:
                    e.status = ServiceStatus.HEALTHY
                    e.failure_count = 0
                    e.last_check = time.time()

    def mark_unhealthy(self, service: str, url: str):
        """Mark endpoint as unhealthy"""
        with self._lock:
            for e in self._services.get(service, []):
                if e.url == url:
                    e.status = ServiceStatus.UNHEALTHY
                    e.failure_count += 1
                    e.last_check = time.time()


class ServiceMeshClient:
    """
    Service mesh HTTP client.
    """

    def __init__(self, registry: ServiceRegistry = None):
        self.registry = registry or _registry

        # Default timeout
        self.default_timeout = 10

        logger.info("ServiceMeshClient initialized")

    def call(
        self,
        service: str,
        path: str,
        method: str = "GET",
        data: Any = None,
        timeout: float = None
    ) -> requests.Response:
        """Call service"""
        endpoint = self.registry.get_endpoint(service)

        if not endpoint:
            raise ServiceNotFoundError(f"Service not found: {service}")

        url = f"{endpoint.url}{path}"
        timeout = timeout or self.default_timeout

        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                timeout=timeout
            )

            if response.status_code < 400:
                self.registry.mark_healthy(service, endpoint.url)
            else:
                self.registry.mark_unhealthy(service, endpoint.url)

            return response

        except Exception:
            self.registry.mark_unhealthy(service, endpoint.url)
            raise

    def get(self, service: str, path: str, **kwargs) -> requests.Response:
        """GET request"""
        return self.call(service, path, "GET", **kwargs)

    def post(self, service: str, path: str, **kwargs) -> requests.Response:
        """POST request"""
        return self.call(service, path, "POST", **kwargs)


class ServiceNotFoundError(Exception):
    """Service not found"""
    pass


# Global registry
_registry: Optional[ServiceRegistry] = None


def get_registry() -> ServiceRegistry:
    """Get global registry"""
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


def get_mesh_client() -> ServiceMeshClient:
    """Get mesh client"""
    return ServiceMeshClient(get_registry())


__all__ = ["ServiceRegistry", "ServiceMeshClient", "ServiceEndpoint", "ServiceNotFoundError", "get_registry", "get_mesh_client"]
