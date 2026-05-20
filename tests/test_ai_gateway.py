from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_ai_gateway_disabled_mode_never_loads_local_models():
    from backend.core.ai_gateway import AIGateway
    from backend.core.runtime_control import RuntimeControl

    gateway = AIGateway(runtime=RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "low_resource"}))
    status = gateway.status()

    assert status["mode"] == "disabled"
    assert status["enabled"] is False
    assert status["local_models_loaded"] is False
    assert status["always_on_models"] is False
    assert status["provider_order"] == []


def test_ai_gateway_cloud_mode_uses_cloud_provider_only():
    from backend.core.ai_gateway import AIGateway
    from backend.core.runtime_control import RuntimeControl

    gateway = AIGateway(runtime=RuntimeControl(environ={"AIO_AI_MODE": "cloud"}))
    status = gateway.status()

    assert status["mode"] == "cloud"
    assert status["enabled"] is True
    assert status["provider_order"] == ["cloud"]
    assert status["local_models_loaded"] is False


def test_ai_gateway_api_exposes_runtime_policy(monkeypatch):
    monkeypatch.setenv("AIO_AI_MODE", "hybrid")
    from backend.api.ai_gateway import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/ai/gateway/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "hybrid"
    assert body["enabled"] is True
    assert body["always_on_models"] is False
    assert "cloud" in body["provider_order"]


def test_ai_gateway_router_registered_in_api_registry():
    from backend.app.router_registry import API_ROUTER_SPECS

    names = {spec.name for spec in API_ROUTER_SPECS}

    assert "ai_gateway" in names


def test_ai_runtime_status_uses_gateway_when_ai_disabled(monkeypatch):
    monkeypatch.setenv("AIO_AI_MODE", "disabled")
    import backend.api.ai_enterprise as ai_mod

    def fail_if_loaded():
        raise AssertionError("local_first_runtime_should_not_load")

    monkeypatch.setattr(ai_mod, "get_runtime", fail_if_loaded)

    app = FastAPI()
    app.include_router(ai_mod.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/ai/runtime/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "disabled"
    assert body["enabled"] is False
    assert body["local_models_loaded"] is False


def test_ai_onnx_classify_rejects_when_ai_disabled(monkeypatch):
    monkeypatch.setenv("AIO_AI_MODE", "disabled")
    import backend.api.ai_enterprise as ai_mod

    class Plane:
        def classify(self, payload):
            raise AssertionError("onnx_plane_should_not_run")

    monkeypatch.setattr(ai_mod, "get_onnx_control_plane", lambda: Plane())

    app = FastAPI()
    app.include_router(ai_mod.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post("/api/v1/ai/onnx/classify", json={"subject": "Hello"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "AI is disabled by runtime policy"


def test_ai_onnx_validate_and_evaluate_reject_when_ai_disabled(monkeypatch):
    monkeypatch.setenv("AIO_AI_MODE", "disabled")
    import backend.api.ai_enterprise as ai_mod

    class Plane:
        def validate_model(self, model_name):
            raise AssertionError("validate_should_not_run")

        def evaluate_model(self, *args, **kwargs):
            raise AssertionError("evaluate_should_not_run")

    monkeypatch.setattr(ai_mod, "get_onnx_control_plane", lambda: Plane())

    app = FastAPI()
    app.include_router(ai_mod.router, prefix="/api/v1")
    client = TestClient(app)

    validate = client.post("/api/v1/ai/onnx/validate", json={"model_name": "tiny"})
    evaluate = client.post("/api/v1/ai/onnx/evaluate", json={"model_name": "tiny", "cases": []})

    assert validate.status_code == 409
    assert evaluate.status_code == 409
