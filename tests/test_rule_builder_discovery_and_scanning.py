import json
from pathlib import Path

from fastapi.testclient import TestClient


def _client_with_rules_db(tmp_path, monkeypatch):
    from backend.api import routes, rules
    from backend.db.database import Database
    from backend.main import app

    db = Database(str(tmp_path / "rule-builder.db"))
    monkeypatch.setattr(routes, "_db", db)
    monkeypatch.setattr(rules, "db", db)
    rules.reload_rule_engine()
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")
    return client, db


def _seed_mailbox(db, provider="gmail", email="user1@example.com"):
    return db.upsert_account(
        provider=provider,
        email=email,
        status="connected",
        auth_type="oauth" if provider in {"gmail", "outlook"} else "app_password",
        sync_status="active",
    )


def _seed_attachment_email(db, account_id, message_id, subject="", body_text="", attachment_text=""):
    email_id = db.add_email(
        account_id=account_id,
        message_id=message_id,
        subject=subject,
        sender="Billing Team",
        sender_email="billing@example.com",
        body_text=body_text,
        category="General",
        confidence=0.75,
        priority="Medium",
    )
    metadata = {
        "attachments": [
            {
                "filename": "invoice.pdf",
                "content_type": "application/pdf",
                "text": attachment_text,
            }
        ]
    }
    db.execute("UPDATE emails SET metadata = ? WHERE id = ?", (json.dumps(metadata), email_id))
    return email_id


def test_default_demo_rules_are_not_active_for_new_client(tmp_path, monkeypatch):
    client, _ = _client_with_rules_db(tmp_path, monkeypatch)

    response = client.get("/api/v1/rules")

    assert response.status_code == 200
    names = {rule["name"] for rule in response.json()["rules"]}
    assert names == set()
    assert {
        "Quarantine suspected scams",
        "Move invoices to Finance",
        "Move OTPs to security",
        "Archive old newsletters",
        "Flag urgent emails",
    }.isdisjoint(names)


def test_gmail_folder_label_discovery_saves_provider_ids(tmp_path, monkeypatch):
    from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy

    _, db = _client_with_rules_db(tmp_path, monkeypatch)
    mailbox_id = _seed_mailbox(db, "gmail", "user1@example.com")

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""
        reason = "OK"

        def json(self):
            return {
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {"id": "Label_42", "name": "Finance", "type": "user", "color": {"backgroundColor": "#0b804b"}},
                ]
            }

    monkeypatch.setattr(ProviderMailboxTaxonomy, "_gmail_token", lambda self, account: "token-for-user1")
    monkeypatch.setattr("backend.core.mailbox_taxonomy.requests.get", lambda *args, **kwargs: FakeResponse())

    result = ProviderMailboxTaxonomy(db).sync_mailbox_structure(mailbox_id)

    assert result["ok"] is True
    labels = db.get_all_labels(mailbox_id, include_shared=False)
    folders = db.get_all_folders(mailbox_id, include_shared=False)
    assert {row["provider_label_id"] for row in labels} == {"INBOX", "Label_42"}
    assert {row["provider_folder_id"] for row in folders} == {"INBOX", "Label_42"}
    assert all(row["mailbox_id"] == mailbox_id for row in labels + folders)


def test_sync_structure_endpoint_refreshes_selected_mailbox_only(tmp_path, monkeypatch):
    from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy

    client, db = _client_with_rules_db(tmp_path, monkeypatch)
    first = _seed_mailbox(db, "gmail", "user1@example.com")
    second = _seed_mailbox(db, "gmail", "user2@example.com")
    calls = []

    def fake_sync(self, mailbox_id):
        calls.append(mailbox_id)
        self.db.ensure_mail_folder(mailbox_id, "Finance", provider_folder_id=f"folder-{mailbox_id}", synced_to_provider=True)
        self.db.ensure_mail_label(mailbox_id, "Finance", provider_label_id=f"label-{mailbox_id}", synced_to_provider=True)
        return {"ok": True, "folders_synced": 1, "labels_synced": 1, "mailbox_id": mailbox_id}

    monkeypatch.setattr(ProviderMailboxTaxonomy, "sync_mailbox_structure", fake_sync)

    response = client.post(f"/api/v1/mailboxes/{second}/sync-structure")

    assert response.status_code == 200
    assert calls == [second]
    assert db.get_all_folders(first, include_shared=False) == []
    assert {row["provider_folder_id"] for row in db.get_all_folders(second, include_shared=False)} == {f"folder-{second}"}


def test_rule_simulation_scans_attachment_text_without_modifying_email(tmp_path, monkeypatch):
    client, db = _client_with_rules_db(tmp_path, monkeypatch)
    mailbox_id = _seed_mailbox(db, "gmail", "user1@example.com")
    email_id = _seed_attachment_email(
        db,
        mailbox_id,
        "msg-attachment-only",
        attachment_text="GST invoice amount 1200 due date 2026-06-01",
    )

    created = client.post("/api/v1/rules", json={
        "name": "Move invoice attachments",
        "mailbox_scope": "selected",
        "mailbox_id": mailbox_id,
        "scan_scope": "entire_email_with_attachments",
        "match_mode": "any",
        "condition": {"type": "attachment_content_contains", "value": ["invoice"]},
        "actions": [{"type": "move_to_folder", "value": "Finance"}],
        "apply_existing": False,
    })
    assert created.status_code == 200
    rule_id = created.json()["rule_id"]

    simulated = client.post(f"/api/v1/rules/{rule_id}/simulate", json={"mailbox_id": mailbox_id, "limit": 20})

    assert simulated.status_code == 200
    payload = simulated.json()
    assert payload["dry_run"] is True
    assert payload["matched_count"] == 1
    assert payload["scanned_count"] == 1
    assert payload["matches"][0]["email_id"] == email_id
    assert payload["matches"][0]["matched_source"] == "attachment_content"
    assert "would move to folder Finance" in payload["matches"][0]["planned_actions"]
    assert db.fetch_one("SELECT folder FROM emails WHERE id = ?", (email_id,))["folder"] == "INBOX"


def test_rule_simulation_extracts_text_attachment_path(tmp_path, monkeypatch):
    client, db = _client_with_rules_db(tmp_path, monkeypatch)
    mailbox_id = _seed_mailbox(db, "gmail", "user1@example.com")
    attachment_path = tmp_path / "receipt.txt"
    attachment_path.write_text("GST invoice from stored attachment path", encoding="utf-8")
    email_id = db.add_email(
        account_id=mailbox_id,
        message_id="msg-with-file-attachment",
        subject="",
        sender="Billing Team",
        sender_email="billing@example.com",
        body_text="",
        category="General",
        confidence=0.75,
        priority="Medium",
    )
    db.execute(
        "UPDATE emails SET metadata = ? WHERE id = ?",
        (json.dumps({"attachments": [{"filename": "receipt.txt", "path": str(attachment_path), "content_type": "text/plain"}]}), email_id),
    )
    created = client.post("/api/v1/rules", json={
        "name": "Detect text attachments",
        "mailbox_scope": "selected",
        "mailbox_id": mailbox_id,
        "scan_scope": "entire_email_with_attachments",
        "match_mode": "any",
        "condition": {"type": "attachment_content_contains", "value": ["invoice"]},
        "actions": [{"type": "add_label", "value": "Finance"}],
        "apply_existing": False,
    })
    rule_id = created.json()["rule_id"]

    simulated = client.post(f"/api/v1/rules/{rule_id}/simulate", json={"mailbox_id": mailbox_id})

    assert simulated.status_code == 200
    assert simulated.json()["matched_count"] == 1
    assert simulated.json()["matches"][0]["matched_source"] == "attachment_content"
    indexed = db.fetch_one("SELECT attachment_text, scan_status FROM emails WHERE id = ?", (email_id,))
    assert "GST invoice" in indexed["attachment_text"]
    assert indexed["scan_status"] == "indexed"


def test_imap_label_creation_is_provider_visible_folder_backed(tmp_path, monkeypatch):
    from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy

    client, db = _client_with_rules_db(tmp_path, monkeypatch)
    mailbox_id = _seed_mailbox(db, "imap", "user1@example.com")

    def fake_create_folder(self, account, name):
        return self._ok(f"imap-folder:{name}", "IMAP folder-backed label created.", {"folder_backed": True, "folder_name": name})

    monkeypatch.setattr(ProviderMailboxTaxonomy, "_create_imap_folder", fake_create_folder)

    response = client.post(f"/api/v1/mailboxes/{mailbox_id}/labels", json={"name": "Finance"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["remote"]["remote"] is True
    assert payload["remote"]["folder_backed"] is True
    labels = db.get_all_labels(mailbox_id, include_shared=False)
    folders = db.get_all_folders(mailbox_id, include_shared=False)
    assert labels[0]["synced_to_provider"] == 1
    assert labels[0]["provider_label_id"] == "imap-folder:Finance"
    assert folders[0]["provider_folder_id"] == "imap-folder:Finance"


def test_imap_label_action_copies_to_remote_label_folder(tmp_path, monkeypatch):
    from backend.rules.action_executor import IMAPProviderActionAdapter

    _, db = _client_with_rules_db(tmp_path, monkeypatch)
    mailbox_id = _seed_mailbox(db, "imap", "user1@example.com")
    email_id = db.add_email(
        account_id=mailbox_id,
        message_id="42",
        subject="Invoice",
        sender="Billing",
        sender_email="billing@example.com",
        body_text="invoice",
        category="General",
        confidence=0.8,
        priority="Medium",
    )
    email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
    calls = []

    class FakeIMAP:
        def create(self, folder):
            calls.append(("create", folder))
            return "OK", []

        def select(self, folder):
            calls.append(("select", folder))
            return "OK", []

        def uid(self, command, uid, folder):
            calls.append(("uid", command, uid, folder))
            return "OK", []

        def logout(self):
            calls.append(("logout",))

    monkeypatch.setattr(IMAPProviderActionAdapter, "_connect", lambda self: FakeIMAP())

    result = IMAPProviderActionAdapter(mailbox_id, db).apply(email, "add_label", "Finance")

    assert result["success"] is True
    assert result["provider_label_id"] == "imap-folder:Finance"
    assert ("create", "Finance") in calls
    assert ("uid", "COPY", "42", "Finance") in calls


def test_rule_apply_is_mailbox_scoped_and_logs_attachment_match(tmp_path, monkeypatch):
    client, db = _client_with_rules_db(tmp_path, monkeypatch)
    first = _seed_mailbox(db, "gmail", "user1@example.com")
    second = _seed_mailbox(db, "gmail", "user2@example.com")
    first_email = _seed_attachment_email(db, first, "msg-user1", attachment_text="invoice for user one")
    second_email = _seed_attachment_email(db, second, "msg-user2", attachment_text="invoice for user two")

    rule = client.post("/api/v1/rules", json={
        "name": "User one invoice rule",
        "mailbox_scope": "selected",
        "mailbox_id": first,
        "scan_scope": "entire_email_with_attachments",
        "match_mode": "any",
        "condition": {"type": "attachment_content_contains", "value": ["invoice"]},
        "actions": [{"type": "move_to_folder", "value": "Finance"}],
        "apply_existing": False,
    }).json()

    applied = client.post(f"/api/v1/rules/{rule['rule_id']}/apply", json={"limit": 20, "provider_write": False})

    assert applied.status_code == 200
    assert applied.json()["matched_count"] == 1
    assert db.fetch_one("SELECT folder FROM emails WHERE id = ?", (first_email,))["folder"] == "Finance"
    assert db.fetch_one("SELECT folder FROM emails WHERE id = ?", (second_email,))["folder"] == "INBOX"
    logs = db.fetch_all("SELECT * FROM rule_execution_logs ORDER BY id")
    assert len(logs) == 1
    assert logs[0]["mailbox_id"] == first
    assert logs[0]["message_id"] == first_email
    assert logs[0]["matched_source"] == "attachment_content"


def test_automations_frontend_has_client_friendly_rule_builder_copy():
    root = Path(__file__).resolve().parents[1]
    html = (root / "backend" / "dashboard" / "index.html").read_text(encoding="utf-8", errors="replace")

    assert "Entire email including attachments" in html
    assert "Attachment content contains" in html
    assert "Scan folders and labels" in html
    assert "Simulation complete" in html
    assert "No rules created yet. Create your first automation rule." in html
