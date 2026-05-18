from pathlib import Path


def test_dashboard_html_uses_external_stylesheets():
    html = Path("backend/dashboard/index.html").read_text("utf-8")

    assert "style=" not in html
