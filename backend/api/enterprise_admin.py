from __future__ import annotations
from fastapi import APIRouter, Depends
from backend.auth.local_auth import require_local_auth_or_localhost
from backend.db.database import Database
from backend import config

router = APIRouter()
db = Database(config.DB_PATH)
SECTIONS = [
    "User Management", "Roles & Permissions", "Team Management", "System Health", "Rule Management", "Automation Management", "Email Provider Management", "Update Center", "Audit Logs", "Security Center", "Backup Manager", "Database Health", "API Integrations", "Notification Management", "AI Configuration", "Queue Monitoring", "Storage Management", "Maintenance Mode", "Activity Monitoring", "License / Subscription"
]

@router.get("/admin/overview", dependencies=[Depends(require_local_auth_or_localhost)])
async def admin_overview():
    accounts = len(db.get_all_accounts())
    rules = (db.fetch_one("SELECT COUNT(*) AS c FROM rules") or {}).get("c", 0)
    actions = (db.fetch_one("SELECT COUNT(*) AS c FROM rule_action_audit") or {}).get("c", 0)
    sections = []
    for name in SECTIONS:
        sections.append({"name": name, "description": f"Manage {name.lower()} for the email operations platform.", "items": [{"label": "Status", "value": "Ready"}, {"label": "Accounts", "value": accounts}, {"label": "Rules", "value": rules}, {"label": "Actions", "value": actions}]})
    return {"status": "ready", "sections": sections, "count": len(sections)}

@router.get("/admin/audit", dependencies=[Depends(require_local_auth_or_localhost)])
async def admin_audit(limit: int = 100):
    return {"audit": db.fetch_all("SELECT * FROM rule_action_audit ORDER BY created_at DESC LIMIT ?", (min(limit, 1000),)), "count": min(limit, 1000)}
