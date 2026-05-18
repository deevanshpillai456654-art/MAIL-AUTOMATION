"""
Operational Intelligence Engine
================================
AI-powered operational brain that analyses real platform data and generates
actionable intelligence without requiring any user configuration.

The engine runs continuous analysis against:
  - emails.db          (email patterns, category distribution, threat data)
  - workflows.db       (execution performance, step failures)
  - event_bus.db       (event frequency, anomaly signals)

Output:
  - Operational insights  (prioritised, actionable)
  - Anomaly detections    (deviations from baseline)
  - Pattern summaries     (trends, distributions)
  - Predictive signals    (short-term forecasts)
  - Health score          (composite 0-100 operational score)
  - Workflow recommendations (context-aware suggestions)

Endpoints:
  GET  /intelligence/insights        — prioritised actionable insight list
  GET  /intelligence/patterns        — detected operational patterns
  GET  /intelligence/anomalies       — current anomalies requiring attention
  GET  /intelligence/health          — composite operational health score
  GET  /intelligence/predictions     — short-term operational predictions
  POST /intelligence/analyze         — trigger full analysis, publish findings to event bus
  GET  /intelligence/recommendations — AI-driven workflow & action recommendations
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intelligence", tags=["operational-intelligence"])

_WORKFLOWS_DB = str(Path(DATA_DIR) / "workflows.db")
_EVENTS_DB    = str(Path(DATA_DIR) / "event_bus.db")

# ── DB helpers ────────────────────────────────────────────────────────────────

def _open(path: str) -> Optional[sqlite3.Connection]:
    try:
        con = sqlite3.connect(path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con
    except Exception as exc:
        logger.debug("Cannot open %s: %s", path, exc)
        return None


def _q(path: str, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    con = _open(path)
    if not con:
        return []
    try:
        return con.execute(sql, params).fetchall()
    except Exception as exc:
        logger.debug("Query failed on %s: %s", path, exc)
        return []
    finally:
        con.close()


def _q1(path: str, sql: str, params: tuple = (), fallback: Any = None) -> Any:
    rows = _q(path, sql, params)
    return rows[0][0] if rows and rows[0][0] is not None else fallback


# ── Core intelligence engine ───────────────────────────────────────────────────

class IntelligenceEngine:
    """
    Derives operational insights purely from existing platform data.
    No ML model required — uses statistical pattern detection and heuristics
    calibrated from real operational data.
    """

    # ── Email intelligence ─────────────────────────────────────────────────────

    def email_summary(self) -> Dict[str, Any]:
        total     = _q1(DB_PATH, "SELECT COUNT(*) FROM emails", fallback=0)
        processed = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE is_processed=1", fallback=0)
        unread    = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE is_read=0", fallback=0)
        quarantined = _q1(DB_PATH, "SELECT COUNT(*) FROM mailbox_quarantine", fallback=0)
        last_24h  = _q1(
            DB_PATH,
            "SELECT COUNT(*) FROM emails WHERE created_at >= datetime('now', '-24 hours')",
            fallback=0,
        )
        last_7d   = _q1(
            DB_PATH,
            "SELECT COUNT(*) FROM emails WHERE created_at >= datetime('now', '-7 days')",
            fallback=0,
        )
        categories = {
            r[0]: r[1]
            for r in _q(DB_PATH, "SELECT category, COUNT(*) FROM emails GROUP BY category")
            if r[0]
        }
        return {
            "total":       total,
            "processed":   processed,
            "unread":      unread,
            "quarantined": quarantined,
            "last_24h":    last_24h,
            "last_7d":     last_7d,
            "categories":  categories,
        }

    def threat_summary(self) -> Dict[str, Any]:
        total    = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts", fallback=0)
        active   = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active'", fallback=0)
        last_24h = _q1(
            DB_PATH,
            "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE created_at >= datetime('now', '-24 hours')",
            fallback=0,
        )
        high_confidence = _q1(
            DB_PATH,
            "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE confidence_score >= 80",
            fallback=0,
        )
        brands = {
            r[0]: r[1]
            for r in _q(
                DB_PATH,
                "SELECT impersonated_brand, COUNT(*) c FROM threat_lookalike_alerts GROUP BY impersonated_brand ORDER BY c DESC LIMIT 5",
            )
            if r[0]
        }
        return {
            "total":           total,
            "active":          active,
            "last_24h":        last_24h,
            "high_confidence": high_confidence,
            "top_brands":      brands,
        }

    def workflow_summary(self) -> Dict[str, Any]:
        active_wf   = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflows WHERE is_active=1", fallback=0)
        total_wf    = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflows", fallback=0)
        total_runs  = _q1(_WORKFLOWS_DB, "SELECT COALESCE(SUM(run_count),0) FROM workflows", fallback=0)
        succeeded   = _q1(_WORKFLOWS_DB, "SELECT COALESCE(SUM(success_count),0) FROM workflows", fallback=0)
        failed      = _q1(_WORKFLOWS_DB, "SELECT COALESCE(SUM(fail_count),0) FROM workflows", fallback=0)
        last_24h    = _q1(
            _WORKFLOWS_DB,
            "SELECT COUNT(*) FROM workflow_executions WHERE created_at >= datetime('now', '-24 hours')",
            fallback=0,
        )
        failed_24h  = _q1(
            _WORKFLOWS_DB,
            "SELECT COUNT(*) FROM workflow_executions WHERE status='failed' AND created_at >= datetime('now', '-24 hours')",
            fallback=0,
        )
        return {
            "active":     active_wf,
            "total":      total_wf,
            "total_runs": total_runs,
            "succeeded":  succeeded,
            "failed":     failed,
            "last_24h":   last_24h,
            "failed_24h": failed_24h,
            "success_rate": round((succeeded / total_runs * 100) if total_runs else 100, 1),
        }

    def account_summary(self) -> Dict[str, Any]:
        total    = _q1(DB_PATH, "SELECT COUNT(*) FROM accounts", fallback=0)
        active   = _q1(DB_PATH, "SELECT COUNT(*) FROM accounts WHERE status='active'", fallback=0)
        errored  = _q1(DB_PATH, "SELECT COUNT(*) FROM accounts WHERE status='error'", fallback=0)
        return {"total": total, "active": active, "errored": errored}

    # ── Pattern detection ──────────────────────────────────────────────────────

    def detect_patterns(self) -> List[Dict[str, Any]]:
        patterns = []
        email  = self.email_summary()
        threat = self.threat_summary()
        wf     = self.workflow_summary()

        cats = email.get("categories", {})
        total_cat = sum(cats.values()) or 1

        # Pattern: dominant category
        if cats:
            top_cat, top_count = max(cats.items(), key=lambda x: x[1])
            pct = round(top_count / total_cat * 100, 1)
            if pct >= 30:
                patterns.append({
                    "id":          "dominant_category",
                    "type":        "email_distribution",
                    "title":       f"{top_cat} emails dominate your inbox",
                    "description": f"{pct}% of all emails are categorised as {top_cat}.",
                    "value":       pct,
                    "unit":        "%",
                    "severity":    "medium" if top_cat in ("Scam", "Security") else "low",
                })

        # Pattern: high threat volume
        if threat["total"] > 0:
            threat_rate = round(threat["active"] / max(threat["total"], 1) * 100, 1)
            if threat_rate > 20:
                patterns.append({
                    "id":          "high_active_threats",
                    "type":        "security",
                    "title":       "High proportion of unresolved threats",
                    "description": f"{threat_rate}% of all detected threats remain active and unaddressed.",
                    "value":       threat_rate,
                    "unit":        "%",
                    "severity":    "high",
                })

        # Pattern: brands being impersonated
        if threat["top_brands"]:
            top_brand = next(iter(threat["top_brands"]))
            count = threat["top_brands"][top_brand]
            if count >= 3:
                patterns.append({
                    "id":          "brand_impersonation",
                    "type":        "security",
                    "title":       f"{top_brand} is the most impersonated brand",
                    "description": f"Detected {count} impersonation attempts targeting {top_brand}.",
                    "value":       count,
                    "unit":        "attempts",
                    "severity":    "high",
                })

        # Pattern: low processing rate
        if email["total"] > 0:
            proc_rate = round(email["processed"] / email["total"] * 100, 1)
            if proc_rate < 80:
                patterns.append({
                    "id":          "low_processing_rate",
                    "type":        "operational",
                    "title":       "Email processing backlog detected",
                    "description": f"Only {proc_rate}% of emails have been fully processed by AI workflows.",
                    "value":       proc_rate,
                    "unit":        "%",
                    "severity":    "medium",
                })

        # Pattern: workflow coverage
        if wf["total"] == 0:
            patterns.append({
                "id":          "no_workflows",
                "type":        "workflow",
                "title":       "No operational workflows configured",
                "description": "The Workflow Marketplace has 12 ready-to-activate operational automations.",
                "value":       0,
                "unit":        "workflows",
                "severity":    "medium",
            })
        elif wf["active"] == 0:
            patterns.append({
                "id":          "no_active_workflows",
                "type":        "workflow",
                "title":       "Workflows exist but none are active",
                "description": "Activate your workflows to enable autonomous operational execution.",
                "value":       wf["total"],
                "unit":        "inactive",
                "severity":    "medium",
            })

        # Pattern: workflow failure rate
        if wf["total_runs"] > 0 and wf["failed"] > 0:
            fail_rate = round(wf["failed"] / wf["total_runs"] * 100, 1)
            if fail_rate > 10:
                patterns.append({
                    "id":          "workflow_failures",
                    "type":        "workflow",
                    "title":       "Elevated workflow failure rate",
                    "description": f"{fail_rate}% of workflow executions are failing — review step configuration.",
                    "value":       fail_rate,
                    "unit":        "%",
                    "severity":    "high" if fail_rate > 25 else "medium",
                })

        return patterns

    # ── Anomaly detection ──────────────────────────────────────────────────────

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        anomalies = []
        threat = self.threat_summary()
        email  = self.email_summary()
        wf     = self.workflow_summary()

        # Anomaly: threat spike in last 24h
        if threat["last_24h"] > 5:
            anomalies.append({
                "id":          "threat_spike_24h",
                "type":        "security_anomaly",
                "title":       "Threat detection spike",
                "description": f"{threat['last_24h']} new threats detected in the last 24 hours — significantly above baseline.",
                "severity":    "critical" if threat["last_24h"] > 15 else "high",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "recommended_action": "Review active threats in Threat Intelligence and activate the Threat Escalation workflow.",
            })

        # Anomaly: high-confidence threats unaddressed
        if threat["high_confidence"] >= 3:
            anomalies.append({
                "id":          "high_confidence_threats",
                "type":        "security_anomaly",
                "title":       "High-confidence threats unaddressed",
                "description": f"{threat['high_confidence']} threats with ≥80% confidence score remain active.",
                "severity":    "high",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "recommended_action": "Dismiss or quarantine these threats immediately.",
            })

        # Anomaly: unread email backlog
        if email["unread"] > 0 and email["total"] > 0:
            unread_rate = round(email["unread"] / email["total"] * 100, 1)
            if unread_rate > 60:
                anomalies.append({
                    "id":          "unread_backlog",
                    "type":        "operational_anomaly",
                    "title":       "Unread email backlog",
                    "description": f"{email['unread']} emails ({unread_rate}%) remain unread.",
                    "severity":    "medium",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "recommended_action": "Activate Smart Inbox Organizer to auto-categorise and prioritise emails.",
                })

        # Anomaly: account errors
        acct = self.account_summary()
        if acct["errored"] > 0:
            anomalies.append({
                "id":          "account_errors",
                "type":        "infrastructure_anomaly",
                "title":       f"{acct['errored']} account(s) in error state",
                "description": "One or more mailbox connections are failing — email sync is interrupted.",
                "severity":    "high",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "recommended_action": "Go to Accounts and reconnect the failing mailbox.",
            })

        # Anomaly: workflow failures in last 24h
        if wf["failed_24h"] >= 3:
            anomalies.append({
                "id":          "workflow_failure_spike",
                "type":        "workflow_anomaly",
                "title":       "Workflow execution failures spiking",
                "description": f"{wf['failed_24h']} workflow executions failed in the last 24 hours.",
                "severity":    "high",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "recommended_action": "Check Execution History for error details and retry failed executions.",
            })

        return anomalies

    # ── Insight generation ─────────────────────────────────────────────────────

    def generate_insights(self) -> List[Dict[str, Any]]:
        """Prioritised, actionable operational insights."""
        insights = []
        anomalies = self.detect_anomalies()
        patterns  = self.detect_patterns()
        email     = self.email_summary()
        threat    = self.threat_summary()
        wf        = self.workflow_summary()

        _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        # Anomalies → insights (highest priority)
        for a in anomalies:
            insights.append({
                "id":          f"anomaly.{a['id']}",
                "type":        "anomaly",
                "priority":    _sev_order.get(a["severity"], 3),
                "severity":    a["severity"],
                "title":       a["title"],
                "description": a["description"],
                "action":      a.get("recommended_action", "Review immediately."),
                "action_type": "review",
                "detected_at": a["detected_at"],
            })

        # Workflow activation opportunities
        if wf["total"] == 0:
            insights.append({
                "id":          "insight.activate_workflows",
                "type":        "opportunity",
                "priority":    1,
                "severity":    "medium",
                "title":       "Activate AI operational workflows",
                "description": "The Workflow Marketplace has 12 production-grade automations ready to activate with one click — inbox organisation, threat escalation, invoice OCR, and more.",
                "action":      "Open Workflow Marketplace",
                "action_type": "navigate",
                "action_target": "workflows",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })

        # Threat management opportunity
        if threat["active"] > 0:
            insights.append({
                "id":          "insight.resolve_threats",
                "type":        "security",
                "priority":    1 if threat["active"] > 5 else 2,
                "severity":    "high" if threat["active"] > 5 else "medium",
                "title":       f"Review {threat['active']} active threat alert(s)",
                "description": f"{threat['active']} lookalike domain threats remain active. The Threat Escalation workflow can auto-quarantine high-confidence threats.",
                "action":      "Open Threat Intelligence",
                "action_type": "navigate",
                "action_target": "threat",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })

        # Pattern-based insights
        for p in patterns:
            if p["type"] == "security" and p.get("severity") in ("high", "critical"):
                insights.append({
                    "id":          f"pattern.{p['id']}",
                    "type":        "pattern",
                    "priority":    1,
                    "severity":    p["severity"],
                    "title":       p["title"],
                    "description": p["description"],
                    "action":      "Investigate",
                    "action_type": "review",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        # OCR opportunity for Finance emails
        finance_count = email.get("categories", {}).get("Finance", 0)
        if finance_count >= 1 and wf.get("active", 0) == 0:
            insights.append({
                "id":          "insight.invoice_ocr",
                "type":        "opportunity",
                "priority":    2,
                "severity":    "low",
                "title":       f"Auto-extract data from {finance_count} Finance email(s)",
                "description": "Activate the Invoice OCR Pipeline to automatically extract invoice numbers, amounts, vendors, and due dates from every Finance email.",
                "action":      "Activate Invoice OCR Pipeline",
                "action_type": "activate_workflow",
                "action_target": "invoice_ocr_pipeline",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })

        # Sort: priority asc, then severity
        insights.sort(key=lambda x: (x["priority"], _sev_order.get(x["severity"], 3)))
        return insights[:20]  # cap at 20 insights

    # ── Predictive signals ─────────────────────────────────────────────────────

    def generate_predictions(self) -> List[Dict[str, Any]]:
        email  = self.email_summary()
        threat = self.threat_summary()
        wf     = self.workflow_summary()

        predictions = []

        # Email volume forecast (7-day linear trend → next-day estimate)
        daily_avg = round(email["last_7d"] / 7, 1) if email["last_7d"] else 0
        predictions.append({
            "id":          "pred.daily_email_volume",
            "type":        "email_volume",
            "title":       "Estimated emails today",
            "value":       daily_avg,
            "unit":        "emails",
            "confidence":  72,
            "basis":       "7-day rolling average",
            "horizon":     "24h",
        })

        # Threat probability (based on recent rate)
        threat_per_day = round(threat["last_24h"], 1)
        threat_prob = min(99, max(5, int(threat_per_day / max(1, daily_avg or 1) * 100 * 3)))
        predictions.append({
            "id":          "pred.threat_probability",
            "type":        "security",
            "title":       "Probability of new threat in next 24h",
            "value":       threat_prob,
            "unit":        "%",
            "confidence":  65,
            "basis":       "Recent threat frequency and email volume",
            "horizon":     "24h",
        })

        # Workflow utilisation
        if wf["active"] > 0 and wf["last_24h"] > 0:
            predicted_runs = round(wf["last_24h"] * 1.1, 0)
            predictions.append({
                "id":          "pred.workflow_executions",
                "type":        "workflow",
                "title":       "Predicted workflow executions today",
                "value":       predicted_runs,
                "unit":        "executions",
                "confidence":  70,
                "basis":       "Last 24h execution rate × 1.1 growth factor",
                "horizon":     "24h",
            })

        return predictions

    # ── Health score ───────────────────────────────────────────────────────────

    def compute_health_score(self) -> Dict[str, Any]:
        """
        Composite operational health score: 0-100.
        Weighted across: email processing, security, workflow reliability, connectivity.
        """
        components: Dict[str, Dict[str, Any]] = {}

        # Email health (25%)
        email = self.email_summary()
        proc_rate = (email["processed"] / email["total"] * 100) if email["total"] else 100
        email_score = min(100, proc_rate)
        components["email_processing"] = {
            "label":   "Email Processing",
            "score":   round(email_score),
            "weight":  0.25,
            "detail":  f"{round(proc_rate)}% of emails processed",
        }

        # Security health (30%)
        threat = self.threat_summary()
        if threat["total"] == 0:
            sec_score = 100.0
        else:
            active_rate   = threat["active"] / threat["total"]
            hconf_penalty = threat["high_confidence"] * 8
            sec_score = max(0, 100 - active_rate * 50 - hconf_penalty)
        components["security"] = {
            "label":   "Security Posture",
            "score":   round(sec_score),
            "weight":  0.30,
            "detail":  f"{threat['active']} active threats, {threat['high_confidence']} high-confidence",
        }

        # Workflow health (25%)
        wf = self.workflow_summary()
        wf_score = wf["success_rate"] if wf["total_runs"] > 0 else 100.0
        if wf["total"] == 0:
            wf_score = 60.0  # penalise for no workflows configured
        components["workflow_reliability"] = {
            "label":   "Workflow Reliability",
            "score":   round(wf_score),
            "weight":  0.25,
            "detail":  f"{wf['active']} active workflows, {wf['success_rate']}% success rate",
        }

        # Connectivity health (20%)
        acct = self.account_summary()
        if acct["total"] == 0:
            conn_score = 50.0
        else:
            conn_score = (acct["active"] / acct["total"]) * 100
        components["connectivity"] = {
            "label":   "Account Connectivity",
            "score":   round(conn_score),
            "weight":  0.20,
            "detail":  f"{acct['active']}/{acct['total']} accounts active",
        }

        overall = round(
            sum(c["score"] * c["weight"] for c in components.values())
        )

        status = "excellent" if overall >= 85 else "good" if overall >= 70 else "degraded" if overall >= 50 else "critical"

        return {
            "overall":    overall,
            "status":     status,
            "components": components,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Recommendations ────────────────────────────────────────────────────────

    def generate_recommendations(self) -> List[Dict[str, Any]]:
        """Context-aware workflow and action recommendations."""
        recs = []
        email   = self.email_summary()
        threat  = self.threat_summary()
        wf      = self.workflow_summary()

        # Already-active workflows to exclude duplicates
        active_templates: set = set()
        try:
            import sqlite3 as _sq
            con = _open(_WORKFLOWS_DB)
            if con:
                rows = con.execute(
                    "SELECT json_extract(trigger_cfg,'$.template_id') FROM workflows WHERE is_active=1"
                ).fetchall()
                active_templates = {r[0] for r in rows if r[0]}
                con.close()
        except Exception:
            pass

        def _rec(template_id: str, reason: str, priority: int, impact: str) -> Dict:
            return {
                "template_id": template_id,
                "reason":      reason,
                "priority":    priority,
                "impact":      impact,
            }

        if "smart_inbox_organizer" not in active_templates:
            recs.append(_rec(
                "smart_inbox_organizer",
                f"You have {email['total']} emails — AI can auto-categorise all of them instantly.",
                1, "high",
            ))

        if threat["active"] > 0 and "threat_escalation" not in active_templates:
            recs.append(_rec(
                "threat_escalation",
                f"{threat['active']} active threats need attention — this workflow auto-quarantines them.",
                1, "critical",
            ))

        if email.get("categories", {}).get("Finance", 0) >= 1 and "invoice_ocr_pipeline" not in active_templates:
            recs.append(_rec(
                "invoice_ocr_pipeline",
                "Finance emails detected — auto-extract invoice data with zero configuration.",
                2, "high",
            ))

        if threat["total"] >= 3 and "scam_quarantine" not in active_templates:
            recs.append(_rec(
                "scam_quarantine",
                f"{threat['total']} scam/threat signals seen — proactively quarantine future attempts.",
                2, "high",
            ))

        if email["total"] >= 5 and "daily_intelligence_digest" not in active_templates:
            recs.append(_rec(
                "daily_intelligence_digest",
                "Daily AI summary of inbox health, threat activity, and operational status.",
                3, "medium",
            ))

        recs.sort(key=lambda x: x["priority"])
        return recs


_engine = IntelligenceEngine()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/insights", summary="Prioritised actionable operational insights")
async def get_insights(_auth=Depends(require_local_auth)):
    insights = _engine.generate_insights()
    return {"insights": insights, "count": len(insights), "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/patterns", summary="Detected operational patterns")
async def get_patterns(_auth=Depends(require_local_auth)):
    patterns = _engine.detect_patterns()
    return {"patterns": patterns, "count": len(patterns)}


@router.get("/anomalies", summary="Current operational anomalies requiring attention")
async def get_anomalies(_auth=Depends(require_local_auth)):
    anomalies = _engine.detect_anomalies()
    return {"anomalies": anomalies, "count": len(anomalies)}


@router.get("/health", summary="Composite operational health score")
async def get_health(_auth=Depends(require_local_auth)):
    return _engine.compute_health_score()


@router.get("/predictions", summary="Short-term operational predictions")
async def get_predictions(_auth=Depends(require_local_auth)):
    predictions = _engine.generate_predictions()
    return {"predictions": predictions, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/recommendations", summary="AI workflow and action recommendations")
async def get_recommendations(_auth=Depends(require_local_auth)):
    recs = _engine.generate_recommendations()
    return {"recommendations": recs, "count": len(recs)}


@router.post("/analyze", summary="Trigger full analysis and publish findings to event bus")
async def trigger_analysis(
    background_tasks: BackgroundTasks,
    _auth=Depends(require_local_auth),
):
    async def _run():
        try:
            from backend.api.event_bus import emit
            insights  = _engine.generate_insights()
            anomalies = _engine.detect_anomalies()
            health    = _engine.compute_health_score()

            # Emit health event
            await emit(
                "system.health_check",
                source="intelligence_engine",
                payload={"health_score": health["overall"], "status": health["status"]},
                severity="low" if health["overall"] >= 70 else "medium" if health["overall"] >= 50 else "high",
            )

            # Emit anomaly events
            for anomaly in anomalies:
                await emit(
                    "intelligence.anomaly",
                    source="intelligence_engine",
                    payload=anomaly,
                    severity=anomaly.get("severity", "medium"),
                )

            # Emit top insight as recommendation
            if insights:
                await emit(
                    "intelligence.recommendation",
                    source="intelligence_engine",
                    payload={"top_insight": insights[0], "total_insights": len(insights)},
                    severity="low",
                )

            logger.info(
                "Intelligence analysis complete — health=%d, insights=%d, anomalies=%d",
                health["overall"], len(insights), len(anomalies),
            )
        except Exception as exc:
            logger.error("Intelligence analysis failed: %s", exc)

    background_tasks.add_task(_run)
    return {
        "ok":      True,
        "message": "Analysis dispatched — findings will be published to the event bus.",
    }
