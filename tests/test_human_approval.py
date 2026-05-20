from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_human_review_queue_returns_pending_items_for_tenant_only():
    from backend.ai.human_review_queue import HumanReviewQueue

    queue = HumanReviewQueue()
    keep = queue.enqueue("tenant-a", "low_confidence", {"message": "review"})
    done = queue.enqueue("tenant-a", "policy", {"message": "done"})
    queue.enqueue("tenant-b", "policy", {"message": "other"})
    queue.resolve(done, "approved")

    pending = queue.pending_for_tenant("tenant-a")

    assert [item.item_id for item in pending] == [keep]
    assert all(item.tenant_id == "tenant-a" for item in pending)
    assert all(item.status == "pending" for item in pending)


def test_human_review_queue_stats_counts_pending_without_payloads():
    from backend.ai.human_review_queue import HumanReviewQueue

    queue = HumanReviewQueue()
    approved = queue.enqueue("tenant-a", "review", {"secret": "hidden"})
    queue.enqueue("tenant-a", "review", {"secret": "hidden"})
    queue.enqueue("tenant-b", "review", {"secret": "hidden"})
    queue.resolve(approved, "approved")

    stats = queue.stats()

    assert stats == {"pending": 2, "tenants_with_pending": 2}


def test_human_review_queue_resolve_reports_missing_items():
    from backend.ai.human_review_queue import HumanReviewQueue

    queue = HumanReviewQueue()
    item_id = queue.enqueue("tenant-a", "review", {})

    assert queue.resolve(item_id, "approved") is True
    assert queue.resolve("missing", "approved") is False


def test_human_review_queue_rejects_when_full_without_dropping_existing_items():
    from backend.ai.human_review_queue import HumanReviewQueue, HumanReviewQueueFull

    queue = HumanReviewQueue(max_items=1)
    first = queue.enqueue("tenant-a", "review", {"message": "first"})

    try:
        queue.enqueue("tenant-a", "review", {"message": "second"})
    except HumanReviewQueueFull as exc:
        assert "approval queue is full" in str(exc)
    else:
        raise AssertionError("expected queue full rejection")

    pending = queue.pending_for_tenant("tenant-a")
    assert [item.item_id for item in pending] == [first]


def test_human_approval_api_returns_429_when_queue_full(monkeypatch):
    import backend.api.human_approval as approval_mod
    from backend.ai.human_review_queue import HumanReviewQueue
    from backend.auth.local_auth import require_local_auth

    queue = HumanReviewQueue(max_items=1)
    queue.enqueue("tenant-a", "review", {})
    monkeypatch.setattr(approval_mod, "_queue", queue)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: True
    app.include_router(approval_mod.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post("/api/v1/approvals", json={
        "tenant_id": "tenant-a",
        "reason": "human_approval_required",
        "payload": {"action": "send_email"},
    })

    assert resp.status_code == 429
    assert resp.json()["detail"] == "Human approval queue is full. Retry later."


def test_human_approval_api_enqueue_list_and_decide(monkeypatch):
    import backend.api.human_approval as approval_mod
    from backend.ai.human_review_queue import HumanReviewQueue
    from backend.auth.local_auth import require_local_auth

    monkeypatch.setattr(approval_mod, "_queue", HumanReviewQueue())
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: True
    app.include_router(approval_mod.router, prefix="/api/v1")
    client = TestClient(app)

    created = client.post("/api/v1/approvals", json={
        "tenant_id": "tenant-a",
        "reason": "human_approval_required",
        "payload": {"action": "send_email"},
    })
    assert created.status_code == 201
    item_id = created.json()["id"]

    listed = client.get("/api/v1/approvals?tenant_id=tenant-a")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["id"] == item_id

    decided = client.patch(f"/api/v1/approvals/{item_id}", json={"status": "approved"})
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    listed_again = client.get("/api/v1/approvals?tenant_id=tenant-a")
    assert listed_again.json()["count"] == 0


def test_human_approval_router_registered():
    from backend.app.router_registry import API_ROUTER_SPECS

    assert "human_approval" in {spec.name for spec in API_ROUTER_SPECS}


def test_default_human_approval_queue_uses_runtime_service_budget(monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_HUMAN_APPROVAL_QUEUE_LIMIT", "7")

    import importlib
    import backend.api.human_approval as approval_mod

    approval_mod = importlib.reload(approval_mod)

    assert approval_mod.get_human_approval_queue().capacity == 7
