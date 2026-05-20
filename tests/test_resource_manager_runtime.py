"""Runtime policy tests for backend/core/resource_manager.py."""


def test_global_resource_manager_does_not_autostart_when_enterprise_system_disabled(monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_ENTERPRISE_SYSTEM", "false")
    from backend.core import resource_manager as rm

    started = []

    class FakeResourceManager:
        def start(self):
            started.append(True)

    monkeypatch.setattr(rm, "_resource_manager", None)
    monkeypatch.setattr(rm, "ResourceManager", FakeResourceManager)

    manager = rm.get_resource_manager()

    assert isinstance(manager, FakeResourceManager)
    assert started == []
