from pathlib import Path

from backend.auth.local_auth import get_local_token


ADMIN_HEADERS = {"X-Local-Token": get_local_token()}


def test_onnx_control_plane_classifies_with_local_fallback(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    result = plane.classify(
            {
                "subject": "Invoice INV-100 is due",
                "sender": "Billing",
                "sender_email": "billing@vendor.test",
                "body": "Please process the invoice payment today.",
            }
    )

    assert result["category"] == "Finance"
    assert result["source"] == "onnx_fallback_rules"
    assert result["model"]["engine"] in {"onnxruntime", "local_fallback"}
    assert result["self_healing"]["fallback_active"] is True


def test_learning_feedback_overrides_future_sender_classification(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    feedback = plane.record_feedback(
        {
            "sender_email": "alerts@unknown-example.test",
            "sender": "Unknown Alerts",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
            "scope": "sender",
        }
    )

    result = plane.classify(
        {
            "subject": "Plain update",
            "sender": "Unknown Alerts",
            "sender_email": "alerts@unknown-example.test",
            "body": "Nothing suspicious in this text.",
        }
    )

    assert feedback["status"] == "learned"
    assert result["category"] == "Scam"
    assert result["priority"] == "Critical"
    assert result["source"] == "learned_override"
    assert "alerts@unknown-example.test" in result["learning"]["matched_key"]


def test_learning_memory_can_list_and_forget_overrides(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    feedback = plane.record_feedback(
        {
            "sender_email": "alerts@unknown-example.test",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
            "scope": "sender",
        }
    )

    overrides = plane.learning_overrides()
    forgotten = plane.forget_learning_override(feedback["key"])
    result = plane.classify(
        {
            "subject": "Plain update",
            "sender_email": "alerts@unknown-example.test",
            "body": "Nothing suspicious in this text.",
        }
    )

    assert overrides["total"] == 1
    assert overrides["items"][0]["key"] == "sender:alerts@unknown-example.test"
    assert overrides["items"][0]["category"] == "Scam"
    assert forgotten["status"] == "forgotten"
    assert forgotten["key"] == "sender:alerts@unknown-example.test"
    assert plane.learning_overrides()["total"] == 0
    assert result["source"] != "learned_override"


def test_learning_memory_exports_and_imports_overrides(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    source = OnnxAIControlPlane(model_dir=str(tmp_path / "source-models"))
    source.record_feedback(
        {
            "sender_email": "ceo@client.test",
            "predicted_category": "Normal",
            "actual_category": "Investor",
            "priority": "High",
            "scope": "domain",
        }
    )

    exported = source.export_learning_memory()
    target = OnnxAIControlPlane(model_dir=str(tmp_path / "target-models"))
    imported = target.import_learning_memory(exported)
    classified = target.classify(
        {
            "subject": "Quarterly update",
            "sender_email": "founder@client.test",
            "body": "Board and investor note.",
        }
    )

    assert exported["schema_version"] == 1
    assert exported["overrides"]["domain:client.test"]["category"] == "Investor"
    assert imported["status"] == "imported"
    assert imported["imported_overrides"] == 1
    assert classified["source"] == "learned_override"
    assert classified["category"] == "Investor"


def test_learning_memory_import_preview_reports_conflicts_without_mutating(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "vip@client.test",
            "predicted_category": "Normal",
            "actual_category": "Sales",
            "priority": "High",
            "scope": "sender",
        }
    )

    preview = plane.preview_learning_import(
        {
            "schema_version": 1,
            "overrides": {
                "sender:vip@client.test": {
                    "category": "Support",
                    "priority": "Medium",
                    "scope": "sender",
                },
                "sender:new@client.test": {
                    "category": "Leads",
                    "priority": "High",
                    "scope": "sender",
                },
                "invalid-key": {"category": "Scam"},
            },
        }
    )
    current = plane.learning_overrides()

    assert preview["status"] == "review_required"
    assert preview["total_incoming"] == 3
    assert preview["conflict_count"] == 1
    assert preview["new_count"] == 1
    assert preview["invalid_count"] == 1
    assert preview["conflicts"][0]["key"] == "sender:vip@client.test"
    assert preview["conflicts"][0]["existing"]["category"] == "Sales"
    assert preview["conflicts"][0]["incoming"]["category"] == "Support"
    assert current["total"] == 1
    assert current["items"][0]["category"] == "Sales"


def test_onnx_ai_state_backup_restore_roundtrip(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "fraud@client.test",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
        }
    )
    plane.report_model_failure("legacy-classifier", "before_backup")

    backup = plane.create_ai_state_backup(reason="manual_test")
    plane.forget_learning_override("sender:fraud@client.test")
    plane.report_model_failure("other-classifier", "after_backup")
    restored = plane.restore_ai_state_backup(backup["backup_id"])
    classified = plane.classify(
        {
            "subject": "Account warning",
            "sender_email": "fraud@client.test",
            "body": "Please verify now.",
        }
    )
    events = plane.self_healing_status()["events"]

    assert backup["status"] == "created"
    assert backup["files"]["onnx_learning_memory.json"]["exists"] is True
    assert restored["status"] == "restored"
    assert classified["source"] == "learned_override"
    assert classified["category"] == "Scam"
    assert any(event["model"] == "legacy-classifier" for event in events)
    assert not any(event["model"] == "other-classifier" for event in events)
    assert plane.ai_state_backup_status()["total_backups"] >= 1


def test_onnx_ai_state_backup_schedule_creates_only_when_due(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    schedule = plane.configure_ai_state_backup_schedule(enabled=True, interval_seconds=60, retention=2)
    first = plane.run_scheduled_ai_state_backup()
    second = plane.run_scheduled_ai_state_backup()

    assert schedule["enabled"] is True
    assert schedule["interval_seconds"] == 60
    assert schedule["retention"] == 2
    assert first["status"] == "created"
    assert first["backup"]["reason"] == "scheduled"
    assert second["status"] == "skipped"
    assert second["reason"] == "not_due"


def test_learning_audit_events_track_learn_forget_and_import(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    learned = plane.record_feedback(
        {
            "sender_email": "audit@client.test",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
        }
    )
    plane.forget_learning_override(learned["key"])
    plane.import_learning_memory(
        {
            "schema_version": 1,
            "overrides": {
                "sender:lead@client.test": {
                    "category": "Leads",
                    "priority": "High",
                    "scope": "sender",
                }
            },
        }
    )

    events = plane.learning_events(limit=10)
    actions = [event["action"] for event in events["items"]]

    assert events["total"] >= 3
    assert actions[:3] == ["imported", "forgotten", "learned"]
    assert events["items"][0]["key"] == "sender:lead@client.test"
    assert events["items"][0]["actual_category"] == "Leads"


def test_onnx_control_plane_runs_registered_model_when_runtime_is_available(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            features = inputs["features"]
            assert features.shape == (1, 4)
            return [onnx_control_plane.np.array([[0.1, 4.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "investor-classifier.onnx").write_bytes(b"fake model accepted by fake runtime")
    (model_dir / "investor-classifier.labels.json").write_text('{"labels":["Normal","Investor"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    evaluation = plane.evaluate_model(
        "investor-classifier",
        cases=[
            {"subject": "Term sheet update", "body": "Investor diligence package", "expected_category": "Investor"}
        ],
        min_accuracy=1.0,
        activate=True,
    )
    result = plane.classify({"subject": "Term sheet update", "body": "Investor diligence package"})

    assert evaluation["status"] == "accepted"
    assert evaluation["activated"] is True
    assert result["category"] == "Investor"
    assert result["source"] == "onnx_model"
    assert result["model"]["engine"] == "onnxruntime"
    assert result["self_healing"]["fallback_active"] is False


def test_self_healing_quarantines_failed_model_and_uses_fallback(tmp_path):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "broken-classifier.onnx").write_bytes(b"not an onnx model")
    plane = OnnxAIControlPlane(model_dir=str(model_dir))
    models = plane.discover_models()
    assert models

    healing = plane.report_model_failure("broken-classifier", "load_error")
    result = plane.classify({"subject": "security alert", "body": "unusual sign in"})

    assert healing["status"] == "quarantined"
    assert healing["active_model"] is None
    assert result["category"] in {"Security", "Scam"}
    assert result["self_healing"]["fallback_active"] is True
    assert any(event["action"] == "quarantine_model" for event in plane.self_healing_status()["events"])


def test_self_healing_recovers_revalidated_quarantined_model(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            return [onnx_control_plane.np.array([[0.2, 3.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "recoverable-classifier.onnx").write_bytes(b"valid fake onnx model")
    (model_dir / "recoverable-classifier.labels.json").write_text('{"labels":["Normal","Support"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    evaluation = plane.evaluate_model(
        "recoverable-classifier",
        cases=[{"subject": "Support ticket update", "body": "Please help the customer", "expected_category": "Support"}],
        min_accuracy=1.0,
        activate=True,
    )
    plane.report_model_failure("recoverable-classifier", "operator_test")

    recovered = plane.recover_model("recoverable-classifier")
    result = plane.classify({"subject": "Support ticket update", "body": "Please help the customer"})

    assert evaluation["status"] == "accepted"
    assert recovered["status"] == "recovered"
    assert recovered["model"] == "recoverable-classifier"
    assert recovered["active_model"] == "recoverable-classifier"
    assert recovered["fallback_active"] is False
    assert result["category"] == "Support"
    assert result["source"] == "onnx_model"
    assert any(event["action"] == "recover_model" for event in plane.self_healing_status()["events"])


def test_onnx_ai_backend_endpoints_expose_status_classify_and_learning(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    status = client.get("/api/v1/ai/onnx/status", headers=ADMIN_HEADERS)
    assert status.status_code == 200
    assert status.json()["status"] in {"ready", "degraded"}

    feedback = client.post(
        "/api/v1/ai/learning/feedback",
        json={
            "sender_email": "founder@investor-mail.test",
            "predicted_category": "Personal",
            "actual_category": "Investor",
            "priority": "High",
        },
        headers=ADMIN_HEADERS,
    )
    assert feedback.status_code == 200
    assert feedback.json()["status"] == "learned"

    classify = client.post(
        "/api/v1/ai/onnx/classify",
        json={"subject": "Monthly note", "sender_email": "founder@investor-mail.test", "body": "Hello"},
        headers=ADMIN_HEADERS,
    )
    assert classify.status_code == 200
    assert classify.json()["category"] == "Investor"
    assert classify.json()["source"] == "learned_override"


def test_onnx_ai_backend_endpoints_list_and_forget_learning_overrides(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    feedback = client.post(
        "/api/v1/ai/learning/feedback",
        json={
            "sender_email": "vip@client.test",
            "predicted_category": "Normal",
            "actual_category": "Sales",
            "priority": "High",
        },
        headers=ADMIN_HEADERS,
    )
    listed = client.get("/api/v1/ai/learning/overrides", headers=ADMIN_HEADERS)
    forgotten = client.delete("/api/v1/ai/learning/overrides/sender%3Avip%40client.test", headers=ADMIN_HEADERS)

    assert feedback.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["key"] == "sender:vip@client.test"
    assert forgotten.status_code == 200
    assert forgotten.json()["status"] == "forgotten"
    assert client.get("/api/v1/ai/learning/overrides", headers=ADMIN_HEADERS).json()["total"] == 0


def test_onnx_ai_backend_endpoints_export_and_import_learning_memory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    client.post(
        "/api/v1/ai/learning/feedback",
        json={
            "sender_email": "partner@market.test",
            "predicted_category": "Normal",
            "actual_category": "Marketing",
            "priority": "Medium",
            "scope": "domain",
        },
        headers=ADMIN_HEADERS,
    )
    exported = client.get("/api/v1/ai/learning/export", headers=ADMIN_HEADERS)
    client.delete("/api/v1/ai/learning/overrides/domain%3Amarket.test", headers=ADMIN_HEADERS)
    imported = client.post("/api/v1/ai/learning/import", json=exported.json(), headers=ADMIN_HEADERS)

    assert exported.status_code == 200
    assert exported.json()["overrides"]["domain:market.test"]["category"] == "Marketing"
    assert imported.status_code == 200
    assert imported.json()["imported_overrides"] == 1
    assert client.get("/api/v1/ai/learning/overrides", headers=ADMIN_HEADERS).json()["total"] == 1


def test_onnx_ai_backend_learning_admin_actions_require_admin_role(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "sensitive@client.test",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
        }
    )
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)
    payload = {
        "schema_version": 1,
        "overrides": {
            "sender:lead@client.test": {
                "category": "Leads",
                "priority": "High",
                "scope": "sender",
            }
        },
    }

    assert client.get("/api/v1/ai/learning/export").status_code == 401
    assert client.post("/api/v1/ai/learning/import/preview", json=payload).status_code == 401
    assert client.post("/api/v1/ai/learning/import", json=payload).status_code == 401
    assert client.delete("/api/v1/ai/learning/overrides/sender%3Asensitive%40client.test").status_code == 401

    assert client.get("/api/v1/ai/learning/export", headers=ADMIN_HEADERS).status_code == 200
    assert client.post("/api/v1/ai/learning/import/preview", json=payload, headers=ADMIN_HEADERS).status_code == 200
    assert client.post("/api/v1/ai/learning/import", json=payload, headers=ADMIN_HEADERS).status_code == 200
    assert client.delete(
        "/api/v1/ai/learning/overrides/sender%3Asensitive%40client.test",
        headers=ADMIN_HEADERS,
    ).status_code == 200


def test_onnx_ai_backend_endpoint_previews_learning_import_conflicts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "partner@market.test",
            "predicted_category": "Normal",
            "actual_category": "Marketing",
            "priority": "Medium",
        }
    )
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    preview = client.post(
        "/api/v1/ai/learning/import/preview",
        json={
            "schema_version": 1,
            "overrides": {
                "sender:partner@market.test": {
                    "category": "Support",
                    "priority": "High",
                    "scope": "sender",
                },
                "domain:lead.test": {
                    "category": "Leads",
                    "priority": "High",
                    "scope": "domain",
                },
            },
        },
        headers=ADMIN_HEADERS,
    )

    assert preview.status_code == 200
    assert preview.json()["status"] == "review_required"
    assert preview.json()["conflict_count"] == 1
    assert preview.json()["new_count"] == 1
    assert plane.learning_overrides()["items"][0]["category"] == "Marketing"


def test_onnx_ai_backend_endpoint_exposes_learning_events(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    client.post(
        "/api/v1/ai/learning/feedback",
        json={
            "sender_email": "audit@client.test",
            "predicted_category": "Normal",
            "actual_category": "Support",
            "priority": "High",
        },
        headers=ADMIN_HEADERS,
    )
    events = client.get("/api/v1/ai/learning/events", headers=ADMIN_HEADERS)

    assert events.status_code == 200
    assert events.json()["total"] == 1
    assert events.json()["items"][0]["action"] == "learned"
    assert events.json()["items"][0]["key"] == "sender:audit@client.test"


def test_onnx_ai_backend_endpoint_recovers_quarantined_model(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane
    from fastapi.testclient import TestClient
    from backend.api import ai_enterprise
    from backend.main import app

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            return [onnx_control_plane.np.array([[0.1, 2.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "support-classifier.onnx").write_bytes(b"valid fake onnx model")
    (model_dir / "support-classifier.labels.json").write_text('{"labels":["Normal","Support"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    plane.evaluate_model(
        "support-classifier",
        cases=[{"subject": "Support ticket", "body": "Please help", "expected_category": "Support"}],
        min_accuracy=1.0,
        activate=True,
    )
    plane.report_model_failure("support-classifier", "manual_failure_report")
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    recovered = client.post("/api/v1/ai/self-healing/models/support-classifier/recover", headers=ADMIN_HEADERS)

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "recovered"
    assert recovered.json()["active_model"] == "support-classifier"


def test_onnx_evaluation_gate_blocks_activation_until_accuracy_passes(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            return [onnx_control_plane.np.array([[0.1, 4.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "investor-classifier.onnx").write_bytes(b"fake model accepted by fake runtime")
    (model_dir / "investor-classifier.labels.json").write_text('{"labels":["Normal","Investor"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    before = plane.status()
    rejected = plane.evaluate_model(
        "investor-classifier",
        cases=[{"subject": "Support ticket", "expected_category": "Support"}],
        min_accuracy=1.0,
        activate=True,
    )
    accepted = plane.evaluate_model(
        "investor-classifier",
        cases=[{"subject": "Investor update", "expected_category": "Investor"}],
        min_accuracy=1.0,
        activate=True,
    )

    assert before["active_model"] is None
    assert rejected["status"] == "rejected"
    assert rejected["activated"] is False
    assert rejected["accuracy"] == 0.0
    assert plane.status()["active_model"] == "investor-classifier"
    assert accepted["status"] == "accepted"
    assert accepted["activated"] is True
    assert accepted["checksum_sha256"]


def test_onnx_evaluation_backend_endpoint_runs_activation_gate(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane
    from fastapi.testclient import TestClient
    from backend.api import ai_enterprise
    from backend.main import app

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            return [onnx_control_plane.np.array([[0.1, 4.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "sales-classifier.onnx").write_bytes(b"fake model accepted by fake runtime")
    (model_dir / "sales-classifier.labels.json").write_text('{"labels":["Normal","Sales"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    evaluated = client.post(
        "/api/v1/ai/onnx/evaluate",
        json={
            "model_name": "sales-classifier",
            "min_accuracy": 1.0,
            "activate": True,
            "cases": [{"subject": "Sales lead", "expected_category": "Sales"}],
        },
        headers=ADMIN_HEADERS,
    )

    assert evaluated.status_code == 200
    assert evaluated.json()["status"] == "accepted"
    assert evaluated.json()["activated"] is True
    assert plane.status()["active_model"] == "sales-classifier"


def test_onnx_ai_backend_model_admin_actions_require_admin_role(tmp_path, monkeypatch):
    import backend.ai.onnx_control_plane as onnx_control_plane
    from fastapi.testclient import TestClient
    from backend.api import ai_enterprise
    from backend.main import app

    class FakeInput:
        name = "features"
        shape = [1, 4]

    class FakeSession:
        def __init__(self, path, providers=None):
            self.path = path
            self.providers = providers

        def get_inputs(self):
            return [FakeInput()]

        def run(self, output_names, inputs):
            return [onnx_control_plane.np.array([[0.2, 4.0]], dtype=onnx_control_plane.np.float32)]

    class FakeOrt:
        InferenceSession = FakeSession

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "support-classifier.onnx").write_bytes(b"valid fake onnx model")
    (model_dir / "support-classifier.labels.json").write_text('{"labels":["Normal","Support"]}', encoding="utf-8")
    monkeypatch.setattr(onnx_control_plane, "ort", FakeOrt)

    plane = onnx_control_plane.OnnxAIControlPlane(model_dir=str(model_dir))
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)
    evaluation_body = {
        "model_name": "support-classifier",
        "min_accuracy": 1.0,
        "activate": True,
        "cases": [{"subject": "Support ticket", "expected_category": "Support"}],
    }

    assert client.post("/api/v1/ai/onnx/evaluate", json=evaluation_body).status_code == 401
    assert plane.status()["active_model"] is None
    assert client.post("/api/v1/ai/onnx/evaluate", json=evaluation_body, headers=ADMIN_HEADERS).status_code == 200
    assert plane.status()["active_model"] == "support-classifier"

    assert client.post("/api/v1/ai/self-healing/models/support-classifier/failure").status_code == 401
    assert plane.status()["active_model"] == "support-classifier"
    assert client.post(
        "/api/v1/ai/self-healing/models/support-classifier/failure",
        headers=ADMIN_HEADERS,
    ).status_code == 200
    assert client.post("/api/v1/ai/self-healing/models/support-classifier/recover").status_code == 401
    assert client.post(
        "/api/v1/ai/self-healing/models/support-classifier/recover",
        headers=ADMIN_HEADERS,
    ).status_code == 200


def test_onnx_ai_backend_backup_restore_requires_admin_and_restores_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import ai_enterprise
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "board@investor.test",
            "predicted_category": "Normal",
            "actual_category": "Investor",
            "priority": "High",
        }
    )
    monkeypatch.setattr(ai_enterprise, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    assert client.get("/api/v1/ai/backups/status").status_code == 401
    assert client.post("/api/v1/ai/backups/run").status_code == 401
    assert client.post("/api/v1/ai/backups/schedule", json={"enabled": True}).status_code == 401

    schedule = client.post(
        "/api/v1/ai/backups/schedule",
        json={"enabled": True, "interval_seconds": 120, "retention": 3},
        headers=ADMIN_HEADERS,
    )
    created = client.post("/api/v1/ai/backups/run", headers=ADMIN_HEADERS)
    backup_id = created.json()["backup_id"]
    client.delete("/api/v1/ai/learning/overrides/sender%3Aboard%40investor.test", headers=ADMIN_HEADERS)

    assert schedule.status_code == 200
    assert schedule.json()["schedule"]["interval_seconds"] == 120
    assert created.status_code == 200
    assert client.get("/api/v1/ai/backups/status", headers=ADMIN_HEADERS).json()["total_backups"] >= 1
    assert client.post(f"/api/v1/ai/backups/{backup_id}/restore").status_code == 401
    restored = client.post(f"/api/v1/ai/backups/{backup_id}/restore", headers=ADMIN_HEADERS)
    classified = client.post(
        "/api/v1/ai/onnx/classify",
        json={"subject": "Board deck", "sender_email": "board@investor.test", "body": "Investor update"},
        headers=ADMIN_HEADERS,
    )

    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
    assert classified.json()["source"] == "learned_override"
    assert classified.json()["category"] == "Investor"


def test_reports_include_learning_accuracy_and_model_health(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import enterprise_reports
    from backend.main import app

    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    plane.record_feedback(
        {
            "sender_email": "safe@client.test",
            "predicted_category": "Scam",
            "actual_category": "Normal",
            "priority": "Medium",
        }
    )
    plane.record_feedback(
        {
            "sender_email": "fraud@client.test",
            "predicted_category": "Normal",
            "actual_category": "Scam",
            "priority": "Critical",
        }
    )
    monkeypatch.setattr(enterprise_reports, "get_onnx_control_plane", lambda: plane)
    client = TestClient(app)

    report = client.get("/api/v1/reports/summary", headers=ADMIN_HEADERS)
    exported = client.get("/api/v1/reports/export.csv", headers=ADMIN_HEADERS)

    assert report.status_code == 200
    assert report.json()["learning"]["scam_false_positives"] == 1
    assert report.json()["learning"]["scam_false_negatives"] == 1
    assert report.json()["learning"]["learning_corrections"] == 2
    assert report.json()["model_health"]["onnx_fallback_rate"] == "100%"
    assert "learning,scam_false_positives,1" in exported.text
    assert "model_health,onnx_fallback_rate,100%" in exported.text


def test_package_exposes_onnx_evaluation_command():
    import json

    package = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["onnx:evaluate"] == "python -B scripts/evaluate_onnx_models.py"


def test_ai_processing_frontend_exposes_onnx_learning_and_self_healing_controls():
    root = Path(__file__).resolve().parents[1]
    html = (root / "backend" / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (root / "backend" / "dashboard" / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (root / "backend" / "dashboard" / "enterprise-ui.css").read_text(encoding="utf-8")

    assert "onnxHealthGrid" in html
    assert "onnxRecoveryList" in html
    assert "learningMemoryList" in html
    assert "learningAuditList" in html
    assert "learningFeedbackForm" in html
    assert "learningImportPreview" in html
    assert "previewLearningImportBtn" in html
    assert "aiBackupList" in html
    assert "learningReport" in html
    assert "modelHealthReport" in html
    assert "/api/v1/ai/onnx/status" in js
    assert "/api/v1/ai/onnx/classify" in js
    assert "/api/v1/ai/learning/feedback" in js
    assert "/api/v1/ai/learning/overrides" in js
    assert "/api/v1/ai/learning/events" in js
    assert "/api/v1/ai/learning/export" in js
    assert "/api/v1/ai/learning/import/preview" in js
    assert "/api/v1/ai/learning/import" in js
    assert "/api/v1/ai/self-healing/models/" in js
    assert "/api/v1/ai/backups/status" in js
    assert "X-Intemo-Role" in js
    assert "renderOnnxStatus" in js
    assert "recoverOnnxModel" in js
    assert "renderLearningMemory" in js
    assert "previewLearningImport" in js
    assert "renderLearningImportPreview" in js
    assert "forgetLearningOverride" in js
    assert "loadLearningAudit" in js
    assert "renderLearningAudit" in js
    assert "exportLearningMemory" in js
    assert "importLearningMemory" in js
    assert "backupAiState" in js
    assert "restoreAiStateBackup" in js
    assert "state.reports.learning" in js
    assert "state.reports.model_health" in js
    assert "submitLearningFeedback" in js
    assert ".onnx-health-grid" in css
    assert ".onnx-recovery-list" in css
    assert ".learning-memory-list" in css
    assert ".learning-audit-list" in css
    assert ".learning-memory-transfer" in css
    assert ".learning-import-preview" in css
    assert ".learning-import-conflict" in css
    assert ".ai-backup-panel" in css
    assert ".model-health-report" in css
    assert ".learning-feedback-panel" in css
