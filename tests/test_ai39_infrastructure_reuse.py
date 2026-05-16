import json

import pytest


def test_folder_and_label_creation_reuses_existing_equivalent_structure(tmp_path):
    from backend.db.database import Database

    db = Database(str(tmp_path / "infra-reuse.db"))
    user_id = db.add_user("owner@example.com", "gmail")
    account_id = db.add_account(user_id, "owner@example.com", "gmail")

    sales_folder_id = db.ensure_mail_folder(account_id, "Sales")
    support_label_id = db.ensure_mail_label(account_id, "Support")

    assert db.ensure_mail_folder(account_id, "AI_Sales") == sales_folder_id
    assert db.ensure_mail_folder(account_id, "Smart Sales") == sales_folder_id
    assert db.ensure_mail_label(account_id, "Smart_Support") == support_label_id
    assert db.ensure_mail_label(account_id, "Auto Support") == support_label_id

    folders = db.fetch_all("SELECT name FROM mail_folders WHERE account_id = ? ORDER BY name", (account_id,))
    labels = db.fetch_all("SELECT name FROM mail_labels WHERE account_id = ? ORDER BY name", (account_id,))

    assert [row["name"] for row in folders] == ["Sales"]
    assert [row["name"] for row in labels] == ["Support"]


def test_provider_infrastructure_sync_populates_reusable_labels_and_folders(tmp_path):
    from backend.db.database import Database

    db = Database(str(tmp_path / "infra-sync.db"))
    user_id = db.add_user("owner@example.com", "outlook")
    account_id = db.add_account(user_id, "owner@example.com", "outlook")

    summary = db.sync_existing_infrastructure(
        account_id,
        {
            "folders": [{"displayName": "Finance"}, {"name": "Clients"}],
            "labels": [{"name": "Leads"}],
            "categories": [{"displayName": "Support"}],
            "forwarding_rules": [{"id": "fw-1", "to": ["crm@example.com"], "condition": "sales@"}],
        },
        provider="outlook",
    )

    assert summary["folders_synced"] == 2
    assert summary["labels_synced"] == 2
    assert summary["forwarding_synced"] == 1
    assert db.ensure_mail_folder(account_id, "AI_Finance") == db.ensure_mail_folder(account_id, "Finance")
    assert db.ensure_mail_label(account_id, "Smart_Leads") == db.ensure_mail_label(account_id, "Leads")
    assert db.find_existing_forwarding_flow(account_id, ["crm@example.com"], "sales@")


def test_equivalent_rules_and_forwarding_flows_are_not_duplicated(tmp_path):
    from backend.db.database import Database

    db = Database(str(tmp_path / "infra-rules.db"))
    user_id = db.add_user("owner@example.com", "gmail")
    account_id = db.add_account(user_id, "owner@example.com", "gmail")

    condition = json.dumps({"type": "subject_contains", "value": ["demo"]}, sort_keys=True)
    first = db.add_rule(
        user_id,
        "Sales demo routing",
        condition,
        json.dumps([{"type": "move_to_folder", "value": "Sales"}], sort_keys=True),
    )
    second = db.add_rule(
        user_id,
        "AI Sales demo routing",
        condition,
        json.dumps([{"type": "move_to_folder", "value": "AI_Sales"}], sort_keys=True),
    )

    assert second == first
    assert len(db.fetch_all("SELECT * FROM rules WHERE user_id = ?", (user_id,))) == 1

    db.sync_existing_infrastructure(
        account_id,
        {"forwarding_rules": [{"id": "fw-sales", "to": ["crm@example.com"], "condition": {"type": "sender_contains", "value": ["sales@"]}}]},
        provider="gmail",
    )
    with pytest.raises(ValueError, match="existing forwarding workflow"):
        db.add_rule(
            user_id,
            "Duplicate sales forward",
            json.dumps({"type": "sender_contains", "value": ["sales@"]}, sort_keys=True),
            json.dumps([{"type": "forward_email", "value": {"to": ["crm@example.com"]}}], sort_keys=True),
        )


def test_forwarding_to_source_account_is_blocked_as_loop(tmp_path):
    from backend.core.email_forwarding import UniversalEmailForwarder
    from backend.db.database import Database

    db = Database(str(tmp_path / "forward-loop.db"))
    user_id = db.add_user("support@example.com", "gmail")
    account_id = db.add_account(user_id, "support@example.com", "gmail")
    email_id = db.add_email(
        account_id=account_id,
        message_id="m-1",
        subject="Support issue",
        sender="Client",
        sender_email="client@example.com",
        body_text="Need help.",
    )
    email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))

    result = UniversalEmailForwarder(db, enable_provider_write=False).forward_email(
        email,
        {"to": ["support@example.com"]},
        rule_name="Looping support forward",
    )

    assert result["success"] is False
    assert result["provider"]["loop_blocked"] is True
    assert not db.get_forward_audit()
