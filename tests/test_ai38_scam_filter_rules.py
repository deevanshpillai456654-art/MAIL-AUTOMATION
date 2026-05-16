import asyncio


def test_scam_filter_marks_high_risk_email():
    from backend.ai.classifier import EmailClassifier

    result = EmailClassifier().classify(
        subject="Urgent account verification required before wire release",
        sender="Security Desk",
        sender_email="alerts@paypa1-login.example",
        body=(
            "Your account will be suspended today. Verify your account at "
            "https://bit.ly/release-wire and confirm the new bank details."
        ),
    )

    assert result["category"] == "Scam"
    assert result["confidence"] >= 0.85
    assert result["priority"] in {"High", "Critical"}
    assert result.get("scam_reasons")


def test_manual_scam_and_normal_feedback_persists_for_future_sender(tmp_path):
    from backend.ai.classifier import EmailClassifier
    from backend.db.database import Database

    db = Database(str(tmp_path / "scam-feedback.db"))
    user_id = db.add_user("admin@example.com", "local")
    account_id = db.add_account(user_id, "owner@example.com", "gmail")
    email_id = db.add_email(
        account_id=account_id,
        message_id="m-1",
        subject="Vendor update",
        sender="Vendor",
        sender_email="vendor@example.com",
        body_text="Routine status update.",
        category="Personal",
        confidence=0.5,
        priority="Medium",
    )

    db.record_classification_override(email_id=email_id, category="Scam", user_id=user_id)
    scam_result = EmailClassifier(db=db).classify(
        subject="New status update",
        sender="Vendor",
        sender_email="vendor@example.com",
        body="Plain update with no obvious scam phrases.",
    )
    assert scam_result["category"] == "Scam"
    assert scam_result["source"] == "manual_override"

    db.record_classification_override(email_id=email_id, category="Normal", user_id=user_id)
    normal_result = EmailClassifier(db=db).classify(
        subject="New status update",
        sender="Vendor",
        sender_email="vendor@example.com",
        body="Plain update with no obvious scam phrases.",
    )
    assert normal_result["category"] == "Normal"
    assert normal_result["source"] == "manual_override"


def test_category_update_api_applies_scam_feedback_flow(tmp_path):
    from backend.api import routes
    from backend.db.database import Database

    db = Database(str(tmp_path / "scam-route.db"))
    user_id = db.add_user("operator@example.com", "local")
    account_id = db.add_account(user_id, "owner@example.com", "gmail")
    email_id = db.add_email(
        account_id=account_id,
        message_id="m-2",
        subject="Suspicious invoice",
        sender="Unknown",
        sender_email="unknown@example.net",
        body_text="Click this link to release payment.",
        category="Personal",
        confidence=0.5,
        priority="Medium",
    )

    routes._db = db
    routes._classifier = None

    result = asyncio.run(
        routes.update_email_category(
            email_id,
            routes.CategoryUpdateInput(category="Scam", user_id=user_id),
        )
    )

    updated = db.fetch_one("SELECT category, folder, labels, priority FROM emails WHERE id = ?", (email_id,))
    override = db.get_classification_override("unknown@example.net", user_id=user_id)

    assert result["status"] == "success"
    assert result["future_filter"]["category"] == "Scam"
    assert updated["category"] == "Scam"
    assert updated["folder"] == "Scam"
    assert "Scam" in (updated["labels"] or "")
    assert updated["priority"] == "Critical"
    assert override["category"] == "Scam"


def test_scam_verdict_teaches_onnx_learning_memory(tmp_path, monkeypatch):
    from backend.ai.onnx_control_plane import OnnxAIControlPlane
    from backend.api import routes
    from backend.db.database import Database

    db = Database(str(tmp_path / "scam-onnx-learning.db"))
    user_id = db.add_user("operator@example.com", "local")
    account_id = db.add_account(user_id, "owner@example.com", "gmail")
    email_id = db.add_email(
        account_id=account_id,
        message_id="m-onnx-1",
        subject="Vendor account update",
        sender="Vendor Desk",
        sender_email="vendor@example.com",
        body_text="Routine status update.",
        category="Personal",
        confidence=0.5,
        priority="Medium",
    )
    plane = OnnxAIControlPlane(model_dir=str(tmp_path / "models"))
    routes._db = db
    routes._classifier = None
    monkeypatch.setattr(routes, "get_onnx_control_plane", lambda: plane, raising=False)

    result = asyncio.run(
        routes.save_scam_filter_verdict(
            routes.ScamVerdictInput(email_id=email_id, category="Scam", user_id=user_id)
        )
    )
    learned = plane.learning_overrides()
    future = plane.classify(
        {
            "subject": "Another plain update",
            "sender": "Vendor Desk",
            "sender_email": "vendor@example.com",
            "body": "No obvious scam language.",
        }
    )

    assert result["status"] == "success"
    assert result["learning_feedback"]["status"] == "learned"
    assert learned["items"][0]["key"] == "sender:vendor@example.com"
    assert learned["items"][0]["category"] == "Scam"
    assert future["source"] == "learned_override"
    assert future["category"] == "Scam"


def test_default_rules_include_scam_quarantine():
    from backend.rules.engine import RuleAction, build_rule_engine

    engine = build_rule_engine(include_defaults=True)
    matches = [
        rule
        for rule in engine.rules
        if rule.name == "Quarantine suspected scams"
        and rule.match({"category": "Scam", "subject": "anything", "body_text": ""})
    ]

    assert matches, "Default rules must quarantine scam-classified emails"
    action_types = {action["type"] for action in matches[0].actions}
    action_values = {str(action["value"]) for action in matches[0].actions}
    assert RuleAction.MOVE_TO_FOLDER.value in action_types
    assert RuleAction.ADD_LABEL.value in action_types
    assert RuleAction.SET_PRIORITY.value in action_types
    assert "Scam" in action_values
    assert "Critical" in action_values


def test_business_preset_packs_cover_requested_categories():
    from backend.rules.engine import RULE_PRESET_PACKS

    required = {
        "marketing": "Marketing",
        "sales": "Sales",
        "social-media": "Social Media",
        "investor": "Investor",
        "support": "Support",
        "leads": "Leads",
    }

    for preset_id, category in required.items():
        pack = RULE_PRESET_PACKS[preset_id]
        assert pack["rule_count"] == len(pack["rules"]) >= 1
        assert category in pack["folders"]
        assert category.lower().replace(" ", "-") in pack["tags"]
        serialized = str(pack["rules"])
        assert category in serialized
