from pathlib import Path

from fastapi.testclient import TestClient


def _client_with_db(tmp_path, monkeypatch):
    from backend.api import routes
    from backend.db.database import Database
    from backend.main import app

    db = Database(str(tmp_path / "mailbox-isolation.db"))
    monkeypatch.setattr(routes, "_db", db)
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")
    return client, db


def _seed_two_mailboxes(db):
    first = db.upsert_account(
        provider="gmail",
        email="user1@example.com",
        status="connected",
        auth_type="oauth",
        sync_status="active",
    )
    second = db.upsert_account(
        provider="gmail",
        email="user2@example.com",
        status="connected",
        auth_type="oauth",
        sync_status="active",
    )
    first_msg = db.add_email(
        account_id=first,
        message_id="gmail-user1-msg",
        subject="Message for user one",
        sender="Sender One",
        sender_email="sender1@example.com",
        body_text="First mailbox body",
        category="Clients",
        confidence=0.91,
        priority="High",
    )
    second_msg = db.add_email(
        account_id=second,
        message_id="gmail-user2-msg",
        subject="Message for user two",
        sender="Sender Two",
        sender_email="sender2@example.com",
        body_text="Second mailbox body",
        category="Finance",
        confidence=0.92,
        priority="Medium",
    )
    db.ensure_mail_folder(first, "Client Work")
    db.ensure_mail_folder(second, "Finance Work")
    db.ensure_mail_label(first, "VIP")
    db.ensure_mail_label(second, "Payroll")
    db.add_email_label(first_msg, "VIP")
    db.add_email_label(second_msg, "Payroll")
    return first, second, first_msg, second_msg


def test_inbox_all_accounts_and_mailbox_filter_are_account_scoped(tmp_path, monkeypatch):
    client, db = _client_with_db(tmp_path, monkeypatch)
    first, second, _, _ = _seed_two_mailboxes(db)

    all_accounts = client.get("/api/v1/inbox").json()
    second_only = client.get(f"/api/v1/inbox?mailbox_id={second}").json()

    assert all_accounts["count"] == 2
    assert {item["email_address"] for item in all_accounts["emails"]} == {"user1@example.com", "user2@example.com"}
    assert {item["mailbox_id"] for item in all_accounts["emails"]} == {first, second}
    assert second_only["count"] == 1
    assert second_only["emails"][0]["mailbox_id"] == second
    assert second_only["emails"][0]["email_address"] == "user2@example.com"


def test_folder_and_label_lists_do_not_cross_mailboxes(tmp_path, monkeypatch):
    client, db = _client_with_db(tmp_path, monkeypatch)
    first, second, _, _ = _seed_two_mailboxes(db)

    first_folders = client.get(f"/api/v1/mailboxes/{first}/folders").json()["folders"]
    second_folders = client.get(f"/api/v1/mailboxes/{second}/folders").json()["folders"]
    first_labels = client.get(f"/api/v1/mailboxes/{first}/labels").json()["labels"]
    second_labels = client.get(f"/api/v1/mailboxes/{second}/labels").json()["labels"]

    assert {row["name"] for row in first_folders} == {"Client Work"}
    assert {row["name"] for row in second_folders} == {"Finance Work"}
    assert {row["name"] for row in first_labels} == {"VIP"}
    assert {row["name"] for row in second_labels} == {"Payroll"}


def test_create_folder_and_label_target_selected_mailbox_only(tmp_path, monkeypatch):
    from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy

    client, db = _client_with_db(tmp_path, monkeypatch)
    first, second, _, _ = _seed_two_mailboxes(db)
    calls = []

    def fake_folder(self, account, name):
        calls.append(("folder", account["id"], account["email"], name))
        return {"remote": True, "provider_id": f"remote-folder-{account['id']}", "message": "created remotely"}

    def fake_label(self, account, name):
        calls.append(("label", account["id"], account["email"], name))
        return {"remote": True, "provider_id": f"remote-label-{account['id']}", "message": "created remotely"}

    monkeypatch.setattr(ProviderMailboxTaxonomy, "create_remote_folder", fake_folder)
    monkeypatch.setattr(ProviderMailboxTaxonomy, "create_remote_label", fake_label)

    folder_response = client.post(f"/api/v1/mailboxes/{second}/folders", json={"name": "Approvals"}).json()
    label_response = client.post(f"/api/v1/mailboxes/{second}/labels", json={"name": "Escalated"}).json()

    assert folder_response["folder"]["mailbox_id"] == second
    assert label_response["label"]["mailbox_id"] == second
    assert ("folder", second, "user2@example.com", "Approvals") in calls
    assert ("label", second, "user2@example.com", "Escalated") in calls
    assert all(call[1] != first for call in calls)


def test_sync_selected_and_sync_all_are_mailbox_scoped(tmp_path, monkeypatch):
    from backend.api import routes

    client, db = _client_with_db(tmp_path, monkeypatch)
    first, second, _, _ = _seed_two_mailboxes(db)
    calls = []

    class FakeOrchestrator:
        def __init__(self, db_arg):
            self.db = db_arg

        def validate_account(self, account_id, operation="sync"):
            account = self.db.get_account_by_id(account_id)
            return {"ok": True, "account": account}

        def sync_account(self, account_id, max_results=50, sync_id=None):
            calls.append(account_id)
            if account_id == second:
                return {"ok": False, "status": "sync_failed", "message": "second failed"}
            return {"ok": True, "status": "synced", "account_id": account_id, "detail": {"processed": 1}}

    monkeypatch.setattr(routes, "MailboxOrchestrator", FakeOrchestrator)

    selected = client.post(f"/api/v1/mailboxes/{first}/sync").json()
    all_result = client.post("/api/v1/sync/all").json()

    assert selected["account_id"] == first
    assert calls[0] == first
    assert {job["account_id"] for job in all_result["jobs"]} == {first, second}
    assert any(job["status"] == "failed" and job["account_id"] == second for job in all_result["jobs"])
    assert calls.count(first) >= 2
    assert calls.count(second) == 1


def test_frontend_visible_sources_have_no_mojibake():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "backend" / "dashboard" / "index.html",
        root / "backend" / "dashboard" / "enterprise-ui.js",
        root / "backend" / "dashboard" / "enterprise-ui.css",
    ]
    broken = ("âˆ", "â€¦", "â€™", "â€œ", "â€", "Ã", "�")

    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in broken:
            if marker in text:
                offenders.append(f"{path.name}:{marker}")

    assert offenders == []


def test_inbox_header_copy_is_clean():
    root = Path(__file__).resolve().parents[1]
    html = (root / "backend" / "dashboard" / "index.html").read_text(encoding="utf-8", errors="replace")

    assert "Enterprise Inbox" in html
    assert "Threaded conversations with AI summaries and workflow actions." in html
    assert ">Select All<" in html
    assert "â˜‘ Select All" not in html
