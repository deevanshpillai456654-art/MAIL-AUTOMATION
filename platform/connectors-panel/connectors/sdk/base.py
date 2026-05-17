"""
ConnectorBase — abstract base class for all MailPilot connectors.

Every connector subclasses this and provides:
  - MANIFEST: ConnectorManifest
  - sync(entity, since)
  - handle_webhook(event_type, payload)
  - health_check()
  - get_auth_url / exchange_code / refresh_token  (if OAuth)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .manifest import ConnectorManifest
from .retry import retry_async, is_transient_error
from .rate_limiter import get_rate_limiter

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False


def _utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ConnectorBase(ABC):
    """
    Base class for all MailPilot connectors.

    Lifecycle:
        registry.install(connector_id, tenant_id, config)
            -> on_install()
        registry.uninstall(connector_id, tenant_id)
            -> on_uninstall()
        worker triggers -> sync()
        inbound webhook -> handle_webhook()
    """

    MANIFEST: ConnectorManifest  # must be set by subclass

    # Rate limits (override per connector)
    RATE_PER_SECOND: float = 10.0
    RATE_BURST: float = 20.0

    def __init__(self, instance_id: str, tenant_id: str, config: Dict[str, Any], db) -> None:
        """
        Args:
            instance_id: The installed connector record ID (connectors.id).
            tenant_id: Tenant this instance belongs to.
            config: Decrypted connector config dict.
            db: ConnectorPanelDB instance.
        """
        self.instance_id = instance_id
        self.tenant_id = tenant_id
        self.config = config
        self.db = db
        self.log = logging.getLogger(f"connector.{self.MANIFEST.id}.{tenant_id[:8]}")
        self._rl = get_rate_limiter(self.MANIFEST.id, tenant_id,
                                    self.RATE_PER_SECOND, self.RATE_BURST)
        self._http: Optional[Any] = None  # httpx.AsyncClient, lazy init

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    def _get_http(self, **kwargs) -> Any:
        if not _HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required. pip install httpx")
        if self._http is None or self._http.is_closed:
            import httpx
            self._http = httpx.AsyncClient(timeout=30.0, **kwargs)
        return self._http

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Rate-limited HTTP request with transient error retry."""
        import httpx
        await self._rl.acquire()

        async def _do():
            client = self._get_http()
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

        return await retry_async(
            _do,
            max_attempts=3,
            retryable_exceptions=(httpx.HTTPStatusError, httpx.RequestError),
        )

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Token storage helpers (uses existing oauth_tokens table)
    # ------------------------------------------------------------------

    def _store_token(self, access_token: str, refresh_token: Optional[str],
                     expires_at: Optional[str], scopes: List[str]) -> str:
        from ...shared.utils import encrypt_secret
        token_id = f"tok_{uuid.uuid4().hex}"
        now = _utc()
        self.db.execute(
            """INSERT INTO oauth_tokens
               (id, connector_id, tenant_id, provider,
                access_token_enc, refresh_token_enc,
                expires_at, scopes, is_valid, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)
               ON CONFLICT(connector_id, tenant_id, provider)
               DO UPDATE SET
                 access_token_enc=excluded.access_token_enc,
                 refresh_token_enc=excluded.refresh_token_enc,
                 expires_at=excluded.expires_at,
                 scopes=excluded.scopes,
                 is_valid=1""",
            (token_id, self.instance_id, self.tenant_id,
             self.MANIFEST.id,
             encrypt_secret(access_token),
             encrypt_secret(refresh_token) if refresh_token else None,
             expires_at,
             json.dumps(scopes),
             now),
        )
        return token_id

    def _get_token(self) -> Optional[Dict[str, Any]]:
        from ...shared.utils import decrypt_secret
        row = self.db.fetch_one(
            "SELECT * FROM oauth_tokens WHERE connector_id=? AND tenant_id=? AND provider=?",
            (self.instance_id, self.tenant_id, self.MANIFEST.id),
        )
        if not row:
            return None
        tok: Dict[str, Any] = dict(row)
        tok["access_token"] = decrypt_secret(tok["access_token_enc"])
        tok["refresh_token"] = decrypt_secret(tok["refresh_token_enc"]) if tok.get("refresh_token_enc") else None
        return tok

    def _invalidate_token(self) -> None:
        self.db.execute(
            "UPDATE oauth_tokens SET is_valid=0 WHERE connector_id=? AND tenant_id=?",
            (self.instance_id, self.tenant_id),
        )

    # ------------------------------------------------------------------
    # Queue helpers (uses existing queue_jobs table)
    # ------------------------------------------------------------------

    def _enqueue(self, job_type: str, payload: Dict[str, Any],
                 delay_seconds: int = 0, max_attempts: int = 3) -> str:
        job_id = f"job_{uuid.uuid4().hex}"
        now = _utc()
        run_at = now  # simplified: immediate scheduling
        self.db.execute(
            """INSERT INTO queue_jobs
               (id, connector_id, tenant_id, job_type, status,
                payload_json, attempts, max_attempts, created_at, updated_at)
               VALUES (?,?,?,?,'queued',?,0,?,?,?)""",
            (job_id, self.instance_id, self.tenant_id, job_type,
             json.dumps(payload), max_attempts, now, now),
        )
        return job_id

    def _complete_job(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE queue_jobs SET status='completed', updated_at=? WHERE id=?",
            (_utc(), job_id),
        )

    def _fail_job(self, job_id: str, error: str, increment_attempts: bool = True) -> None:
        if increment_attempts:
            self.db.execute(
                """UPDATE queue_jobs
                   SET status=CASE WHEN attempts+1>=max_attempts THEN 'dead' ELSE 'failed' END,
                       attempts=attempts+1, error=?, updated_at=?
                   WHERE id=?""",
                (error[:500], _utc(), job_id),
            )
        else:
            self.db.execute(
                "UPDATE queue_jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (error[:500], _utc(), job_id),
            )

    # ------------------------------------------------------------------
    # Event publishing (uses the 'events' table)
    # ------------------------------------------------------------------

    def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event_id = f"evt_{uuid.uuid4().hex}"
        self.db.execute(
            """INSERT INTO events
               (id, event_type, source_connector_id, tenant_id, payload_json, published_at)
               VALUES (?,?,?,?,?,?)""",
            (event_id, event_type, self.instance_id,
             self.tenant_id, json.dumps(payload), _utc()),
        )

    # ------------------------------------------------------------------
    # Logging (uses the 'connector_logs' table; column is 'timestamp')
    # ------------------------------------------------------------------

    def _log(self, level: str, message: str, extra: Optional[Dict] = None) -> None:
        log_id = f"log_{uuid.uuid4().hex}"
        self.db.execute(
            """INSERT INTO connector_logs
               (id, connector_id, tenant_id, level, message, metadata_json, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (log_id, self.instance_id, self.tenant_id, level, message[:1000],
             json.dumps(extra or {}), _utc()),
        )
        getattr(self.log, level.lower(), self.log.info)(message)

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def _record_health(self, healthy: bool, latency_ms: Optional[float] = None,
                       message: str = "") -> None:
        status = "active" if healthy else "degraded"
        self.db.execute(
            """UPDATE connectors
               SET status=?, last_heartbeat=?,
                   health_score=CASE WHEN ? THEN MIN(1.0, health_score+0.1) ELSE MAX(0.0, health_score-0.2) END,
                   failure_count=CASE WHEN ? THEN failure_count ELSE failure_count+1 END
               WHERE id=?""",
            (status, _utc(), healthy, healthy, self.instance_id),
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks (override as needed)
    # ------------------------------------------------------------------

    async def on_install(self) -> None:
        """Called once when the connector is first installed."""
        self._log("INFO", f"{self.MANIFEST.name} installed for tenant {self.tenant_id}")

    async def on_uninstall(self) -> None:
        """Called when the connector is removed."""
        self._log("INFO", f"{self.MANIFEST.name} uninstalled")
        # Clean up tokens
        self.db.execute(
            "DELETE FROM oauth_tokens WHERE connector_id=? AND tenant_id=?",
            (self.instance_id, self.tenant_id),
        )

    async def on_enable(self) -> None:
        self.db.execute("UPDATE connectors SET status='active' WHERE id=?", (self.instance_id,))

    async def on_disable(self) -> None:
        self.db.execute("UPDATE connectors SET status='inactive' WHERE id=?", (self.instance_id,))

    # ------------------------------------------------------------------
    # OAuth (override if connector uses OAuth)
    # ------------------------------------------------------------------

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        raise NotImplementedError(f"{self.MANIFEST.id} does not support OAuth")

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def refresh_access_token(self) -> str:
        """Refresh token and return new access_token."""
        raise NotImplementedError

    async def get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        tok = self._get_token()
        if not tok:
            raise RuntimeError(f"No OAuth token for connector {self.instance_id}. Connect first.")
        # Check expiry
        if tok.get("expires_at"):
            try:
                exp = datetime.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                remaining = (exp - datetime.now(tz=timezone.utc)).total_seconds()
                if remaining < 300:  # refresh 5 min early
                    return await self.refresh_access_token()
            except Exception:
                pass
        return tok["access_token"]

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def sync(self, entity: str, since: Optional[datetime] = None) -> Dict[str, Any]:
        """Perform a full or incremental sync of the given entity type."""

    @abstractmethod
    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        """Process an inbound webhook event."""

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        """Return True if the webhook signature is valid. Subclasses MUST override."""
        return False  # fail-closed: reject all webhooks unless connector verifies them

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return {"healthy": bool, "latency_ms": float, "message": str}."""

    async def run_sync_all(self) -> Dict[str, Any]:
        """Sync all declared entities sequentially."""
        results = {}
        entities = self.MANIFEST.sync.entities if self.MANIFEST.sync else []
        for entity in entities:
            try:
                result = await self.sync(entity)
                results[entity] = {"ok": True, **result}
                self._publish_event(f"{self.MANIFEST.id}.sync.completed",
                                    {"entity": entity, "result": result})
            except Exception as exc:
                results[entity] = {"ok": False, "error": str(exc)}
                self._log("ERROR", f"sync failed for {entity}: {exc}")
                self._publish_event(f"{self.MANIFEST.id}.sync.failed",
                                    {"entity": entity, "error": str(exc)})
        return results
