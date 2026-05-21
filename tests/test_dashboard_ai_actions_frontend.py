from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def _slice(source: str, start: str, end: str) -> str:
    start_idx = source.index(start)
    end_idx = source.index(end, start_idx)
    return source[start_idx:end_idx]


def test_ai_actions_renderer_does_not_emit_raw_icon_names_or_mojibake_separators():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    block = _slice(js, "async function _loadPlaybookList", "async function _loadPbRuns")

    assert "playbookTriggerLabel" in js
    assert "playbookMetaText" in js
    assert "_TRIGGER_ICON" not in block
    assert "settings" not in block
    assert "·" not in block
    assert "Â" not in block


def test_ai_actions_renderer_uses_structured_rows_without_inline_styles():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")
    list_block = _slice(js, "async function _loadPlaybookList", "async function _loadPbRuns")
    runs_block = _slice(js, "async function _loadPbRuns", "async function _openPbRunModal")

    for token in (
        "playbook-list",
        "playbook-item",
        "playbook-trigger-chip",
        "playbook-meta",
        "playbook-actions",
        "playbook-run-list",
        "playbook-run-item",
    ):
        assert token in js
        assert token in css

    assert 'style="' not in list_block
    assert 'style="' not in runs_block
