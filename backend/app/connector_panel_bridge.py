"""
Load the Connector & Plugin Panel into FastAPI.

The panel lives at platform/connectors-panel (hyphen prevents normal import
syntax).  This bridge uses importlib to set up the package namespace so all
relative imports inside the panel work correctly, then calls the panel's own
setup_connector_panel(app) which registers the API router and mounts the
frontend static files at /connectors-panel.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

log = logging.getLogger(__name__)

_CP_DIR = Path(__file__).resolve().parents[2] / "platform" / "connectors-panel"
_PKG = "connectors_panel"


def _load_package(name: str, path: Path) -> types.ModuleType:
    init = path / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, str(init), submodule_search_locations=[str(path)]
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__path__ = [str(path)]
    mod.__package__ = name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = name.rpartition(".")[0]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def register_connector_panel(app) -> bool:
    """
    Register the connector panel with the FastAPI app.
    Returns True on success, False (with a warning log) on failure.
    """
    if not _CP_DIR.exists():
        log.warning("Connector panel directory not found: %s", _CP_DIR)
        return False

    try:
        # Root package
        _load_package(_PKG, _CP_DIR)

        # shared sub-package + modules (no relative deps)
        _load_package(f"{_PKG}.shared", _CP_DIR / "shared")
        for name in ("constants", "utils", "event_bus"):
            f = _CP_DIR / "shared" / f"{name}.py"
            if f.exists():
                _load_module(f"{_PKG}.shared.{name}", f)

        # connectors SDK sub-package — load before backend so relative imports resolve
        _load_package(f"{_PKG}.connectors", _CP_DIR / "connectors")
        _load_package(f"{_PKG}.connectors.sdk", _CP_DIR / "connectors" / "sdk")
        for name in ("manifest", "retry", "rate_limiter", "base", "registry", "worker"):
            f = _CP_DIR / "connectors" / "sdk" / f"{name}.py"
            if f.exists():
                _load_module(f"{_PKG}.connectors.sdk.{name}", f)

        # backend sub-package — load in dependency order
        _load_package(f"{_PKG}.backend", _CP_DIR / "backend")
        for name in (
            "models", "db",
            "connectors", "marketplace", "plugins",
            "oauth", "webhooks", "queues", "logs", "health", "events",
            "erp", "crm", "tracking", "workflows", "support",
            "connector_engine",
        ):
            f = _CP_DIR / "backend" / f"{name}.py"
            if f.exists():
                _load_module(f"{_PKG}.backend.{name}", f)

        # Main router — setup_connector_panel does DB init + API + static mount
        router_mod = _load_module(f"{_PKG}.backend.router", _CP_DIR / "backend" / "router.py")
        router_mod.setup_connector_panel(app)

        log.info("Connector Panel ready — API: /api/connector-panel  UI: /connectors-panel")
        return True

    except Exception as exc:
        log.warning("Connector Panel failed to load: %s", exc, exc_info=True)
        return False


__all__ = ["register_connector_panel"]
