from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def _slice(source: str, start: str, end: str) -> str:
    start_idx = source.index(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_agents_are_first_class_dashboard_navigation_and_view():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

    assert 'data-view="agents"' in html
    assert 'id="view-agents"' in html
    assert 'id="agentSupervisorPanel"' in html
    assert 'id="agentKpiStrip"' in html
    assert 'id="agentGrid"' in html
    assert 'id="agentActionFeed"' in html


def test_agents_dashboard_renderer_is_api_backed_and_styled():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert "PAGES.agents" in js
    assert "initAgentsView" in js
    assert "loadAgentsDashboard" in js
    assert "renderAgentsDashboard" in js
    assert "renderAgentActionFeed" in js
    assert "if (view === 'agents')" in js
    assert "/api/v1/agents/health" in js
    assert "/api/v1/agents/actions?limit=30" in js

    render_block = _slice(js, "function renderAgentsDashboard", "async function runAgentNow")
    for token in (
        "agents-shell",
        "agent-supervisor-panel",
        "agent-kpi-strip",
        "agent-card-grid",
        "agent-card",
        "agent-status-pill",
        "agent-meta-grid",
        "agent-action-feed",
    ):
        assert token in f"{html}\n{js}"
        assert token in css

    assert 'style="' not in render_block
    assert "Â" not in render_block


def test_mobile_sidebar_closes_when_dashboard_navigation_changes_view():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    click_block = _slice(js, "// -- Global click delegation", "// -- Bindings")
    assert "function setSidebarOpen" in js
    assert "$('sidebarOverlay')?.classList.toggle('open', open)" in js
    assert "$('sidebarToggle')?.setAttribute('aria-expanded', String(open))" in js
    assert "showView(target.dataset.view);" in click_block
    assert "setSidebarOpen(false);" in click_block
