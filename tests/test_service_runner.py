from types import SimpleNamespace


def test_stop_service_terminates_listener_on_api_port(monkeypatch):
    import backend.run as runner

    events = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            events.append(("terminate", self.pid))

        def wait(self, timeout):
            events.append(("wait", self.pid, timeout))

    class FakePsutil:
        class NoSuchProcess(Exception):
            pass

        class AccessDenied(Exception):
            pass

        class TimeoutExpired(Exception):
            pass

        @staticmethod
        def net_connections(kind="inet"):
            return [
                SimpleNamespace(
                    status="LISTEN",
                    laddr=SimpleNamespace(ip="127.0.0.1", port=4597),
                    pid=4321,
                )
            ]

        @staticmethod
        def Process(pid):
            return FakeProcess(pid)

    monkeypatch.setattr(runner, "_load_psutil", lambda: FakePsutil, raising=False)

    assert runner.stop_service() is True
    assert events == [("terminate", 4321), ("wait", 4321, 5)]


def test_stop_service_is_idempotent_when_no_listener(monkeypatch):
    import backend.run as runner

    class FakePsutil:
        class NoSuchProcess(Exception):
            pass

        class AccessDenied(Exception):
            pass

        class TimeoutExpired(Exception):
            pass

        @staticmethod
        def net_connections(kind="inet"):
            return []

    monkeypatch.setattr(runner, "_load_psutil", lambda: FakePsutil, raising=False)

    assert runner.stop_service() is False
