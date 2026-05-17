"""
InstallWizard — multi-step install coordinator.

Wraps ConnectorInstaller with a step-by-step state machine suitable for
REST or websocket-driven install flows (e.g. a frontend wizard).

Steps:
  validate  → load manifest, check permissions
  confirm   → frontend presents results, user approves/rejects
  install   → run full install flow
  complete  → done
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


@dataclass
class WizardSession:
    session_id:  str
    plugin_id:   str
    tenant_id:   str
    step:        str = "validate"   # validate | confirm | install | complete | failed
    manifest:    Dict[str, Any] = field(default_factory=dict)
    validation:  Dict[str, Any] = field(default_factory=dict)
    result:      Optional[Dict[str, Any]] = None
    error:       Optional[str] = None
    created_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InstallWizard:
    """
    Stateful install wizard.  Each session is keyed by session_id.

    Usage::

        wizard = InstallWizard(installer)
        sid = wizard.start(manifest, tenant_id="t1")
        validation = wizard.get_session(sid)
        await wizard.confirm_and_install(sid, instance)
    """

    def __init__(self, installer: Any) -> None:
        self._installer = installer
        self._sessions: Dict[str, WizardSession] = {}

    def start(self, manifest: Dict[str, Any], *, tenant_id: str) -> str:
        """
        Begin a wizard session.  Validates the manifest immediately.
        Returns session_id.
        """
        from .permission_validator import PermissionValidator
        pv = PermissionValidator()
        pv_result = pv.filter_manifest(manifest)

        session_id = f"wiz_{uuid.uuid4().hex[:8]}"
        session = WizardSession(
            session_id=session_id,
            plugin_id=manifest.get("plugin_id") or manifest.get("id", "unknown"),
            tenant_id=tenant_id,
            manifest=manifest,
            validation=pv_result.to_dict(),
            step="confirm" if pv_result.valid else "failed",
            error=None if pv_result.valid else f"Rejected permissions: {pv_result.rejected}",
        )
        self._sessions[session_id] = session
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        s = self._sessions.get(session_id)
        if not s:
            return None
        return {
            "session_id": s.session_id,
            "plugin_id":  s.plugin_id,
            "tenant_id":  s.tenant_id,
            "step":       s.step,
            "validation": s.validation,
            "result":     s.result,
            "error":      s.error,
        }

    async def confirm_and_install(
        self,
        session_id: str,
        instance:   Any,
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        s = self._sessions.get(session_id)
        if not s:
            return {"error": "session not found"}
        if s.step != "confirm":
            return {"error": f"Cannot install from step={s.step}"}

        s.step = "install"
        try:
            result = await self._installer.install(
                s.manifest, instance,
                tenant_id=s.tenant_id,
                config=config,
            )
            s.result = result
            s.step   = "complete"
            return result
        except Exception as exc:
            s.step  = "failed"
            s.error = str(exc)
            log.error("InstallWizard: install failed for session=%s: %s", session_id, exc)
            return {"error": str(exc)}

    def abort(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
