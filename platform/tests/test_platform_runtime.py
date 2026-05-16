from pathlib import Path
import sys
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from runtime.plugin_registry import PluginRegistry
from runtime.plugin_loader import PluginLoader
from runtime.health import RuntimeHealthMonitor


def test_plugin_manifests_load_without_core_app():
    registry = PluginRegistry()
    loader = PluginLoader(PLATFORM_ROOT / 'plugins', registry)
    manifests = loader.load_manifests()
    assert len(manifests) >= 7
    assert registry.get('mailpilot.tracking_aggregation') is not None
    health = RuntimeHealthMonitor(registry).snapshot()
    assert health['summary']['enabled'] >= 1
