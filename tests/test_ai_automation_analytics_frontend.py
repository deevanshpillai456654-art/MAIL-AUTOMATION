from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "platform" / "ai-automation" / "frontend"
DASHBOARD = ROOT / "backend" / "dashboard"


def test_ai_automation_analytics_page_has_modern_sections_without_inline_styles():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    match = re.search(r"<!-- Analytics -->(?P<section>.*?)<!-- Settings -->", html, flags=re.S)
    assert match, "Analytics page section should be present"
    section = match.group("section")

    assert 'class="analytics-shell"' in section
    assert 'class="analytics-kpi-grid"' in section
    assert 'class="card analytics-card analytics-outcome-panel"' in section
    assert 'class="analytics-table"' in section
    assert 'id="analyticsKpis"' in section
    assert 'id="analyticsOutcome"' in section
    assert 'id="analyticsWorkflowSpotlight"' in section
    assert 'id="timelineChart"' in section
    assert "style=" not in section


def test_ai_automation_analytics_renderer_exposes_modern_components():
    js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")

    for function_name in (
        "summarizeAnalytics",
        "renderAnalyticsOverview",
        "renderAnalyticsTable",
        "renderTimeline",
    ):
        assert f"function {function_name}" in js

    for token in (
        "analytics-kpi-card",
        "analytics-outcome-bars",
        "analytics-timeline-grid",
        "analytics-workflow-card",
        "analytics-health-cell",
    ):
        assert token in js
        assert f".{token}" in css


def test_main_dashboard_analytics_view_has_modern_operational_layout():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    match = re.search(r"<!-- ----------- ANALYTICS & REPORTS VIEW.*?(?P<section><section class=\"view\" id=\"view-reports\".*?</section>)", html, flags=re.S)
    assert match, "Main dashboard Analytics view should be present"
    section = match.group("section")

    for token in (
        "reports-shell",
        "reports-hero",
        "reportKpiStrip",
        "reportInsightPanel",
        "reportPipeline",
    ):
        assert token in section
    assert "style=" not in section


def test_main_dashboard_analytics_renderer_has_modern_report_components():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    for function_name in (
        "buildReportSummary",
        "renderReportKpis",
        "renderReportInsightPanel",
        "renderReportPipeline",
    ):
        assert f"function {function_name}" in js

    for token in (
        "report-kpi-strip",
        "report-insight-panel",
        "report-pipeline",
        "report-card-modern",
    ):
        assert token in js
        assert f".{token}" in css
