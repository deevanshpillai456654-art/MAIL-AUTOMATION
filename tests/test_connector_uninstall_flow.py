from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(tmp_path):
    import os

    os.environ["CONNECTOR_PANEL_DB_PATH"] = str(tmp_path / "connectors_panel.db")

    from backend.app.connector_panel_bridge import register_connector_panel
    from backend.auth.local_auth import require_local_auth

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    assert register_connector_panel(app) is True
    return TestClient(app)


def test_uninstall_removes_connector_from_installed_list_and_marketplace_state(tmp_path):
    client = _client(tmp_path)
    tenant_id = "default"

    install = client.post(
        "/api/connector-panel/marketplace/connectors/ocr_engine/install",
        json={"connector_id": "ocr_engine", "tenant_id": tenant_id, "config": {}},
    )
    assert install.status_code == 201
    connector_id = install.json()["connector_id"]

    installed = client.get(f"/api/connector-panel/connectors?tenant_id={tenant_id}").json()
    assert [connector["connector_id"] for connector in installed] == [connector_id]

    delete = client.delete(f"/api/connector-panel/connectors/{connector_id}?tenant_id={tenant_id}")
    assert delete.status_code == 200

    assert client.get(f"/api/connector-panel/connectors?tenant_id={tenant_id}").json() == []

    marketplace = client.get(
        f"/api/connector-panel/marketplace/connectors?tenant_id={tenant_id}"
    ).json()
    ocr = next(connector for connector in marketplace if connector["id"] == "ocr_engine")
    assert ocr["is_installed"] is False
