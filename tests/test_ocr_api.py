from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from backend.api import ocr

    monkeypatch.setattr(ocr, "_DB_PATH", str(tmp_path / "ocr_history.db"))
    app = FastAPI()
    app.dependency_overrides[ocr.require_local_auth] = lambda: None
    app.include_router(ocr.router, prefix="/api/v1")
    return TestClient(app)


def test_scan_text_document_extracts_invoice_fields_and_persists_history(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    text = "\n".join(
        [
            "Invoice INV-1001",
            "From: Example Supplies Ltd",
            "Due Date: 2026-05-31",
            "Total: $1,234.50 USD",
        ]
    )

    response = client.post(
        "/api/v1/ocr/scan",
        data={"mode": "auto"},
        files={"file": ("invoice.txt", text.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "invoice.txt"
    assert payload["fields"]["_detected_type"] == "invoice"
    assert payload["fields"]["invoice_number"] == "INV-1001"
    assert payload["fields"]["currency"] == "USD"
    assert payload["word_count"] > 0

    history = client.get("/api/v1/ocr/history").json()["jobs"]
    assert len(history) == 1
    assert history[0]["id"] == payload["job_id"]

    result = client.get(f"/api/v1/ocr/result/{payload['job_id']}").json()
    assert result["fields"]["invoice_number"] == "INV-1001"
    assert result["raw_text"].startswith("Invoice")


def test_raw_mode_returns_text_without_structured_fields(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/ocr/scan",
        data={"mode": "raw"},
        files={"file": ("note.txt", b"Invoice INV-999 Total: 42 USD", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["fields"] == {}


def test_scan_email_uses_inline_html_when_plain_text_is_absent(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/ocr/scan-email",
        json={
            "subject": "Receipt RCPT-44",
            "sender": "billing@example.test",
            "body_html": "<p>Receipt</p><p>Total: $88.00 USD</p>",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Receipt" in payload["raw_text"]
    assert payload["fields"]["currency"] == "USD"
    assert payload["fields"]["_detected_type"] == "receipt"


def test_history_records_can_be_deleted_individually_or_cleared(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    first = client.post(
        "/api/v1/ocr/scan",
        data={"mode": "auto"},
        files={"file": ("one.txt", b"Invoice INV-1", "text/plain")},
    ).json()
    client.post(
        "/api/v1/ocr/scan",
        data={"mode": "auto"},
        files={"file": ("two.txt", b"Invoice INV-2", "text/plain")},
    )

    assert client.delete(f"/api/v1/ocr/history/{first['job_id']}").status_code == 200
    remaining = client.get("/api/v1/ocr/history").json()["jobs"]
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "two.txt"

    assert client.delete("/api/v1/ocr/history").status_code == 200
    assert client.get("/api/v1/ocr/history").json()["jobs"] == []

