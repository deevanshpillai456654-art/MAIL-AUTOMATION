"""Load the AI Automation module into FastAPI.

The module lives at ``platform/ai-automation``. The hyphenated directory name
cannot be imported with normal Python syntax, so this bridge creates a stable
``ai_automation`` package namespace and registers the module API.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

log = logging.getLogger(__name__)

_AI_DIR = Path(__file__).resolve().parents[2] / "platform" / "ai-automation"
_PKG = "ai_automation"


def _load_package(name: str, path: Path) -> types.ModuleType:
    init = path / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name,
        str(init),
        submodule_search_locations=[str(path)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load package {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    mod.__path__ = [str(path)]
    mod.__package__ = name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = name.rpartition(".")[0]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def register_ai_automation_api(app) -> bool:
    """Register the AI automation API router without remounting static files."""
    if not _AI_DIR.exists():
        log.warning("AI automation directory not found: %s", _AI_DIR)
        return False

    try:
        _load_package(_PKG, _AI_DIR)
        _load_package(f"{_PKG}.backend", _AI_DIR / "backend")
        router_mod = _load_module(f"{_PKG}.backend.router", _AI_DIR / "backend" / "router.py")
        configured_router = router_mod.setup()
        app.include_router(configured_router)
        log.info("AI Automation API ready: /api/ai-automation")
        return True
    except Exception as exc:
        log.warning("AI Automation API failed to load: %s", exc, exc_info=True)
        return False


__all__ = ["register_ai_automation_api"]
