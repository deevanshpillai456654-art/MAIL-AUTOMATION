from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def test_threat_dashboard_has_responsive_layout_regions():
    html = (DASHBOARD / "scam-panel.html").read_text(encoding="utf-8")

    for token in (
        'class="threat-header-copy"',
        'class="threat-mobile-nav"',
        'class="threat-dashboard-grid"',
        'class="threat-panel"',
        'class="data-table-wrap threat-table-wrap"',
    ):
        assert token in html


def test_threat_dashboard_css_prevents_text_gaps_and_overflow():
    css = (DASHBOARD / "scam-panel.css").read_text(encoding="utf-8")

    for token in (
        ".threat-header-copy",
        ".threat-mobile-nav",
        ".threat-table-wrap",
        "overflow-x: auto;",
        "overflow-wrap: anywhere;",
        ".table-domain",
        ".table-email",
        ".table-actions",
        ".is-dismissing",
        "@media (max-width: 720px)",
    ):
        assert token in css

    assert "letter-spacing: -" not in css
    assert "letter-spacing: 0;" in css


def test_threat_dashboard_runtime_keeps_duplicate_nav_controls_in_sync():
    js = (DASHBOARD / "scam-panel.js").read_text(encoding="utf-8")

    assert 'document.querySelectorAll(`[data-view="${name}"]`).forEach' in js
    assert "classList.add('is-dismissing')" in js
    assert "classList.remove('is-dismissing')" in js
    assert "row.style.opacity" not in js
    assert "row.style.pointerEvents" not in js
