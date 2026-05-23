from pathlib import Path


DASHBOARD = Path("backend/dashboard")
CONNECTORS = Path("platform/connectors-panel/frontend")


def test_enterprise_spacing_tokens_exist_on_main_and_connector_frontends():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")

    for token, value in {
        "--sp-1": "4px",
        "--sp-2": "8px",
        "--sp-3": "12px",
        "--sp-4": "16px",
        "--sp-5": "20px",
        "--sp-6": "24px",
        "--sp-8": "32px",
        "--sp-10": "40px",
        "--sp-12": "48px",
        "--sp-16": "64px",
    }.items():
        assert f"{token}:  {value};" in dashboard_css or f"{token}: {value};" in dashboard_css
        assert f"{token}:  {value};" in connector_css or f"{token}: {value};" in connector_css


def test_workflow_marketplace_uses_reusable_classes_not_inline_layout_styles():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")

    assert 'class="wf-template-grid"' in dashboard_html
    for selector in [
        ".workflow-stats-strip",
        ".workflow-marketplace-head",
        ".workflow-section-title",
        ".workflow-reco-label",
        ".wf-template-grid",
        ".wf-template-card",
        ".wf-template-head",
        ".wf-template-title",
        ".wf-template-desc",
        ".wf-template-meta",
    ]:
        assert selector in dashboard_css

    workflow_marketplace_start = dashboard_js.index("async function _loadWfMarketplace")
    workflow_marketplace_end = dashboard_js.index("grid.querySelectorAll('.wf-activate-tmpl-btn')")
    workflow_marketplace_js = dashboard_js[workflow_marketplace_start:workflow_marketplace_end]
    assert "wf-template-card" in workflow_marketplace_js
    assert "wf-template-meta" in workflow_marketplace_js
    assert "style=" not in workflow_marketplace_js

    for class_name in [
        "dash-inline-019",
        "dash-inline-020",
        "dash-inline-021",
        "dash-inline-023",
        "dash-inline-024",
    ]:
        assert class_name not in dashboard_html
        assert f".{class_name}" not in dashboard_css


def test_connector_panel_core_layout_uses_enterprise_spacing_tokens():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")

    for selector in [
        ".content { flex:1; overflow-y:auto; padding:var(--sp-5); }",
        ".connector-grid {\n  display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));\n  gap:var(--sp-4); margin-bottom:var(--sp-5);",
        ".connector-card {\n  background:var(--surface); border:1px solid var(--border);\n  border-radius:var(--radius-lg); padding:var(--sp-5);",
        ".connector-actions { display:flex; gap:var(--sp-2); margin-top:var(--sp-1); }",
    ]:
        assert selector in connector_css


def test_connector_panel_static_dashboard_shell_avoids_inline_layout_styles():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_html = (CONNECTORS / "index.html").read_text("utf-8")

    for selector in [
        ".stats-grid--four",
        ".quick-actions-row",
    ]:
        assert selector in connector_css

    dashboard_start = connector_html.index('<div id="sec-dashboard"')
    dashboard_end = connector_html.index('<div id="sec-tally"')
    dashboard_html = connector_html[dashboard_start:dashboard_end]
    assert 'class="stats-grid stats-grid--four"' in dashboard_html
    assert 'class="quick-actions-row"' in dashboard_html
    assert "style=" not in dashboard_html


def test_connector_panel_dashboard_runtime_uses_reusable_list_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".panel-empty-state",
        ".panel-empty-state p",
        ".connector-list-row",
        ".connector-list-name",
        ".connector-list-version",
    ]:
        assert selector in connector_css

    dashboard_start = connector_js.index("async function loadDashboard")
    dashboard_end = connector_js.index("function _setEl")
    dashboard_js = connector_js[dashboard_start:dashboard_end]
    assert "panel-empty-state" in dashboard_js
    assert "connector-list-row" in dashboard_js
    assert "connector-list-name" in dashboard_js
    assert "connector-list-version" in dashboard_js
    assert "style=" not in dashboard_js


def test_connector_panel_marketplace_renderer_uses_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".connector-empty-state",
        ".btn-installed",
    ]:
        assert selector in connector_css

    marketplace_start = connector_js.index("function renderMarketplace")
    marketplace_end = connector_js.index("async function installConnector")
    marketplace_js = connector_js[marketplace_start:marketplace_end]
    assert "connector-empty-state" in marketplace_js
    assert "btn-installed" in marketplace_js
    assert "style=" not in marketplace_js


def test_connector_panel_connector_modals_use_reusable_metadata_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".modal-copy",
        ".modal-meta-grid",
        ".modal-meta-label",
        ".badge-list",
        ".connector-config-status",
        ".settings-row--compact",
        ".form-group--spaced",
    ]:
        assert selector in connector_css

    modals_start = connector_js.index("async function installConnector")
    modals_end = connector_js.index("function updateSidebarVisibility")
    modals_js = connector_js[modals_start:modals_end]
    config_start = connector_js.index("async function configureConnector")
    config_end = connector_js.index("async function saveConnectorConfig")
    config_js = connector_js[config_start:config_end]
    assert "modal-copy" in modals_js
    assert "modal-meta-grid" in modals_js
    assert "badge-list" in modals_js
    assert "connector-config-status" in config_js
    assert "settings-row--compact" in config_js
    assert "form-group--spaced" in config_js
    assert "style=" not in modals_js
    assert "style=" not in config_js


def test_connector_panel_installed_table_uses_reusable_row_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".installed-connector-title",
        ".installed-connector-category",
        ".health-meter-cell",
        ".health-meter-bar",
        ".health-meter-value",
        ".table-actions",
        ".btn-danger-outline",
    ]:
        assert selector in connector_css

    installed_start = connector_js.index("async function loadInstalled")
    installed_end = connector_js.index("function healthClass")
    installed_js = connector_js[installed_start:installed_end]
    assert "installed-connector-title" in installed_js
    assert "health-meter-cell" in installed_js
    assert "health-meter-bar" in installed_js
    assert "btn-danger-outline" in installed_js
    assert "style=" not in installed_js


def test_tally_connection_modal_uses_reusable_spacing_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".two-col--form",
        ".settings-row--tight",
    ]:
        assert selector in connector_css

    tally_start = connector_js.index("function showTallyConfigureModal")
    tally_end = connector_js.index("async function submitTallyConnection")
    tally_js = connector_js[tally_start:tally_end]
    assert "two-col--form" in tally_js
    assert "settings-row--tight" in tally_js
    assert "style=" not in tally_js


def test_connector_panel_operations_blocks_use_reusable_table_and_health_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".table-empty-row",
        ".table-code-cell",
        ".health-empty-state",
        ".health-score--good",
        ".health-score--warn",
        ".health-score--bad",
    ]:
        assert selector in connector_css

    for start_marker, end_marker in [
        ("function renderOAuthTokens", "async function startOAuth"),
        ("async function loadWebhooks", "function createWebhookModal"),
        ("function renderQueueJobs", "async function retryJob"),
        ("async function loadLogs", "function renderLogLine"),
        ("async function loadHealth", "async function loadPlugins"),
    ]:
        start = connector_js.index(start_marker)
        end = connector_js.index(end_marker)
        block = connector_js[start:end]
        assert "style=" not in block

    assert "table-empty-row" in connector_js
    assert "table-code-cell" in connector_js
    assert "btn-danger-outline" in connector_js
    assert "health-empty-state" in connector_js
    assert "health-score--" in connector_js


def test_connector_panel_plugin_permissions_use_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".plugin-subtext",
        ".permission-chip-list",
        ".permission-chip",
        ".permission-grantor",
        ".permission-empty",
        ".permission-matrix-header",
    ]:
        assert selector in connector_css

    for start_marker, end_marker in [
        ("async function loadPlugins", "async function togglePlugin"),
        ("async function viewPluginPerms", "async function grantPermission"),
        ("function renderPermissionsMatrix", "function loadSettings"),
    ]:
        start = connector_js.index(start_marker)
        end = connector_js.index(end_marker)
        block = connector_js[start:end]
        assert "style=" not in block

    assert "plugin-subtext" in connector_js
    assert "permission-chip" in connector_js
    assert "permission-matrix-header" in connector_js


def test_connector_panel_event_feed_uses_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".badge-clickable",
        ".event-feed-row",
        ".event-feed-badge",
        ".event-feed-body",
        ".event-feed-meta",
        ".event-feed-payload",
        ".event-feed-empty",
        ".event-feed-row--new",
    ]:
        assert selector in connector_css

    events_start = connector_js.index("function renderEventTypes")
    events_end = connector_js.index("async function loadPermissions")
    events_js = connector_js[events_start:events_end]
    assert "badge-clickable" in events_js
    assert "event-feed-row" in events_js
    assert "event-feed-empty" in events_js
    assert "style=" not in events_js


def test_connector_panel_erp_purchase_orders_and_vendors_use_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".erp-mini-row",
        ".erp-mini-title",
        ".erp-mini-sub",
        ".erp-mini-amount",
        ".erp-empty-state",
        ".table-link",
    ]:
        assert selector in connector_css

    for start_marker, end_marker in [
        ("async function loadERP", "async function loadVendors"),
        ("async function loadVendors", "function createVendorModal"),
    ]:
        start = connector_js.index(start_marker)
        end = connector_js.index(end_marker)
        block = connector_js[start:end]
        assert "style=" not in block

    assert "erp-mini-row" in connector_js
    assert "table-code-cell" in connector_js
    assert "table-link" in connector_js
    assert "btn-danger-outline" in connector_js


def test_connector_panel_inventory_and_warehouses_use_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".table-row-warn",
        ".table-value-danger",
        ".inventory-current",
        ".warehouse-empty-state",
        ".warehouse-code",
        ".card-actions-inline",
    ]:
        assert selector in connector_css

    for start_marker, end_marker in [
        ("async function loadInvoices", "function createInvoiceModal"),
        ("async function loadInventory", "function createInventoryModal"),
        ("function adjustStockModal", "async function submitStockAdjust"),
        ("async function loadWarehouses", "function createWarehouseModal"),
    ]:
        start = connector_js.index(start_marker)
        end = connector_js.index(end_marker)
        block = connector_js[start:end]
        assert "style=" not in block

    assert "table-row-warn" in connector_js
    assert "table-value-danger" in connector_js
    assert "inventory-current" in connector_js
    assert "warehouse-empty-state" in connector_js
    assert "warehouse-code" in connector_js
    assert "card-actions-inline" in connector_js


def test_connector_panel_crm_sections_use_reusable_classes():
    connector_css = (CONNECTORS / "styles.css").read_text("utf-8")
    connector_js = (CONNECTORS / "app.js").read_text("utf-8")

    for selector in [
        ".crm-stage-title",
        ".crm-stage-count",
        ".crm-stage-value",
        ".crm-pipeline-empty",
        ".pipeline-column",
        ".pipeline-column-head",
        ".pipeline-dot",
        ".pipeline-card",
        ".pipeline-card-meta",
        ".pipeline-card-row",
        ".score-high",
        ".score-medium",
        ".score-low",
        ".stage-badge",
        ".stage-badge--closed-won",
        ".table-value-strong",
    ]:
        assert selector in connector_css

    for start_marker, end_marker in [
        ("async function loadCRM", "const PIPELINE_STAGES"),
        ("async function loadPipeline", "async function loadLeads"),
        ("async function loadLeads", "function createLeadModal"),
        ("async function loadContacts", "function createContactModal"),
        ("async function loadOpportunities", "function createOpportunityModal"),
    ]:
        start = connector_js.index(start_marker)
        end = connector_js.index(end_marker)
        block = connector_js[start:end]
        assert "style=" not in block

    assert "scoreTone(" in connector_js
    assert "stageClass(" in connector_js
    assert "pipeline-column" in connector_js
    assert "btn-danger-outline" in connector_js


def test_workflow_active_and_history_sections_use_reusable_layout_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")

    for selector in [
        ".wf-stat-card",
        ".wf-stat-value",
        ".wf-stat-label",
        ".wf-active-card",
        ".wf-card-actions",
        ".wf-card-meta",
        ".wf-history-scroll",
        ".wf-history-error",
    ]:
        assert selector in dashboard_css

    active_start = dashboard_js.index("async function _loadWfStats")
    active_end = dashboard_js.index("list.querySelectorAll('.wf-run-btn')")
    active_js = dashboard_js[active_start:active_end]
    assert "wf-stat-card" in active_js
    assert "wf-active-card" in active_js
    assert "wf-card-actions" in active_js
    assert "wf-card-meta" in active_js
    assert "style=" not in active_js

    history_start = dashboard_js.index("async function _loadWfHistory")
    history_end = dashboard_js.index("let _alertEditId")
    history_js = dashboard_js[history_start:history_end]
    assert "wf-history-scroll" in history_js
    assert "wf-history-error" in history_js
    assert "style=" not in history_js


def test_change_and_problem_lists_use_reusable_operations_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")

    for selector in [
        ".ops-stat-card",
        ".ops-stat-value",
        ".ops-stat-label",
        ".ops-stats-strip",
        ".ops-filter-select",
        ".ops-compact-button",
        ".ops-panel-spaced",
        ".ops-dialog-panel",
        ".ops-modal-backdrop",
        ".ops-editor-backdrop",
        ".ops-form-row",
        ".ops-form-label",
        ".ops-form-actions",
        ".ops-code-textarea",
        ".ops-helper-text",
        ".ops-fieldset",
        ".ops-table-state",
        ".ops-row-link",
        ".ops-tone-ok",
        ".ops-tone-warn",
        ".ops-tone-danger",
        ".ops-date",
        ".ops-pagination-label",
    ]:
        assert selector in dashboard_css

    for start_marker, end_marker in [
        ("async function _loadCrStats", "async function _openCrDetail"),
        ("async function _loadPrStats", "async function _openPrDetail"),
    ]:
        if start_marker not in dashboard_js:
            continue
        start = dashboard_js.index(start_marker)
        end = dashboard_js.index(end_marker)
        render_block = dashboard_js[start:end]
        assert "ops-stat-card" in render_block
        assert "ops-table-state" in render_block
        assert "ops-row-link" in render_block
        assert "ops-pagination-label" in render_block
        assert "style=" not in render_block


def test_operations_views_do_not_reuse_generated_stat_or_filter_classes():
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    generated_modal_classes = [
        f"dash-inline-{idx:03d}" for idx in range(69, 95)
    ]

    for view_id in [
        "webhooks",
        "playbooks",
        "dispatches",
        "sla",
        "api-keys",
        "maintenance",
        "runbooks",
        "changes",
    ]:
        start = dashboard_html.index(f'id="view-{view_id}"')
        section_start = dashboard_html.rfind("<section", 0, start)
        section_end = dashboard_html.index("</section>", start)
        section = dashboard_html[section_start:section_end]
        for class_name in generated_modal_classes:
            assert class_name not in section

    for class_name in generated_modal_classes:
        assert f".{class_name}" not in dashboard_css


def test_dashboard_telemetry_strip_uses_reusable_action_card_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")

    for selector in [
        ".telemetry-strip",
        ".telemetry-action-card",
        ".telemetry-card-value",
        ".telemetry-card-value.ok",
        ".telemetry-card-value.warn",
        ".telemetry-card-value.danger",
        ".telemetry-card-value.accent",
    ]:
        assert selector in dashboard_css

    strip_start = dashboard_js.index("async function _loadDashIntelStrip")
    strip_end = dashboard_js.index("let _ocrFile")
    strip_js = dashboard_js[strip_start:strip_end]
    assert "scoreTone" in strip_js
    assert "telemetry-action-card" in strip_js
    assert "telemetry-card-value" in strip_js
    assert "style=" not in strip_js

    assert "dash-inline-012" not in dashboard_html
    assert "telemetry-strip" in dashboard_html


def test_notification_drawer_uses_named_layout_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")

    for selector in [
        ".notification-button",
        ".notification-badge",
        ".notification-panel",
        ".notification-panel-head",
        ".notification-title",
        ".notification-subtitle",
        ".notification-action",
        ".notification-close",
        ".notification-drawer-list",
        ".notification-overlay",
        ".ui-inline-actions",
        ".ui-button-row",
    ]:
        assert selector in dashboard_css

    generated_chrome_classes = [f"dash-inline-{idx:03d}" for idx in range(1, 14)]
    for class_name in generated_chrome_classes:
        assert class_name not in dashboard_html
        assert f".{class_name}" not in dashboard_css


def test_sidebar_uses_calm_grouped_enterprise_navigation():
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")

    nav_start = dashboard_html.index('<nav class="main-nav"')
    nav_end = dashboard_html.index("</nav>", nav_start)
    sidebar_nav = dashboard_html[nav_start:nav_end]

    for selector in [
        ".nav-group",
        ".nav-group summary",
        ".nav-group-title",
        ".nav-group-subtitle",
        ".nav-role-chip",
        ".nav-mode-switch",
        ".nav-mode-button",
        ".nav-submenu",
        ".nav-btn.nav-nested",
    ]:
        assert selector in dashboard_css

    for label in [
        "Service Operations",
        "Advanced",
        "Security Insights",
        "Activity Queue",
        "AI Actions",
        "Automation Guides",
        "Service Issues",
        "Change Requests",
        "Risk Overview",
        "Secure Access",
        "Workspace Config",
        "System Updates",
        "Knowledge Base",
        "Releases",
    ]:
        assert label in sidebar_nav

    for old_label in [
        "Threat Intel",
        "Dispatches",
        "Runbooks",
        "Problems",
        "Risk Register",
        "Certificates",
        "Configs",
        "Maintenance",
        "On-call",
        "Flags",
        "Capacity",
        "Knowledge\n",
        "Deployments",
        "Protection & Compliance",
        "Operations Support",
        "Integrations & Access",
        "Infrastructure",
        "Resources & Planning",
    ]:
        assert old_label not in sidebar_nav

    for view_id in [
        "webhooks",
        "playbooks",
        "dispatches",
        "sla",
        "oncall",
        "api-keys",
        "maintenance",
        "runbooks",
        "changes",
        "problems",
        "services",
        "risks",
        "certificates",
        "configs",
        "licenses",
        "budgets",
        "vendors",
        "knowledge",
        "assets",
        "deployments",
    ]:
        assert f'data-view="{view_id}"' in sidebar_nav

    for runtime_api in [
        "function applyNavigationRole",
        "function setNavigationRole",
        "localStorage.getItem('ai36NavRole')",
        "data-nav-role",
    ]:
        assert runtime_api in dashboard_js

    for page_label in [
        "Activity Queue",
        "AI Actions",
        "Webhook Channels",
        "API Access",
        "Service Goals",
        "Team Availability",
        "Automation Guides",
        "Change Requests",
        "Service Issues",
        "Risk Overview",
        "Secure Access",
        "Workspace Settings",
        "Status Markers",
        "System Usage",
        "Releases",
    ]:
        assert page_label in dashboard_js

    for runtime_label in [
        "New Service Goal",
        "Edit Service Goal",
        "New Access Key",
        "Edit Access Key",
        "No system update windows found.",
        "Cancel system update window",
        "Delete system update window",
        "New Automation Guide",
        "Edit Automation Guide",
    ]:
        assert runtime_label in dashboard_js

    for old_runtime_label in [
        "New SLA Policy",
        "Edit SLA Policy",
        "New API Key",
        "Edit API Key",
        "No maintenance windows found.",
        "Cancel maintenance window",
        "Delete maintenance window",
        "New Runbook",
        "Edit Runbook",
    ]:
        assert old_runtime_label not in dashboard_js

    for visible_label in [
        "Webhook Channels",
        "AI Actions",
        "Service Goals",
        "API Access",
        "New Service Goal",
        "New Access Key",
        "New System Update Window",
        "New Automation Guide",
        "Release Tracker",
        "Service Issue Management",
    ]:
        assert visible_label in dashboard_html

    for old_visible_label in [
        "Outbound Webhooks",
        "SLA Tracker",
        "New SLA Policy",
        "SLA breach detection",
        "New API Key",
        "Your New API Key",
        "New Maintenance Window",
        "Edit Maintenance Window",
        "New Runbook",
        "Search runbooks",
        "Runbook</span>",
        "Deployment Tracker",
        "New Deployment",
        "Problem Management",
        "New Problem",
    ]:
        assert old_visible_label not in dashboard_html


def test_dashboard_ocr_runtime_uses_reusable_result_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")

    for selector in [
        ".ocr-result-loading",
        ".ocr-result-error",
        ".ocr-result-meta",
        ".ocr-result-chip",
        ".ocr-result-muted",
        ".ocr-result-section-title",
        ".ocr-result-table",
        ".ocr-result-key",
        ".ocr-result-value",
        ".ocr-result-raw",
        ".ocr-data-table",
        ".ocr-table-text",
        ".ocr-table-muted",
        ".ocr-table-actions",
        ".btn-danger-text",
    ]:
        assert selector in dashboard_css

    for start_marker, end_marker in [
        ("function _renderResult", "async function _loadOcrEmails"),
        ("async function _loadOcrEmails", "function _ocrEmailListClick"),
        ("async function _loadOcrHistory", "list.querySelectorAll('[data-hview]')"),
    ]:
        start = dashboard_js.index(start_marker)
        end = dashboard_js.index(end_marker)
        block = dashboard_js[start:end]
        assert "style=" not in block

    assert "ocr-result-meta" in dashboard_js
    assert "ocr-data-table" in dashboard_js
    assert "btn-danger-text" in dashboard_js


def test_dashboard_ocr_modal_and_batch_use_reusable_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_js = (DASHBOARD / "enterprise-ui.js").read_text("utf-8")

    for selector in [
        ".ocr-modal",
        ".ocr-modal-head",
        ".ocr-modal-title",
        ".ocr-modal-close",
        ".ocr-modal-body",
        ".ocr-batch-file-list",
        ".ocr-batch-actions",
        ".ocr-batch-results",
        ".ocr-batch-file",
        ".ocr-batch-file-name",
        ".ocr-batch-file-size",
        ".ocr-batch-remove",
        ".ocr-batch-summary",
        ".ocr-batch-card",
        ".ocr-batch-card-head",
        ".ocr-batch-status",
        ".ocr-batch-status--ok",
        ".ocr-batch-status--error",
        ".ocr-batch-fields",
        ".ocr-batch-field",
    ]:
        assert selector in dashboard_css

    for start_marker, end_marker in [
        ("function _showOcrModal", "function _downloadJson"),
        ("function _renderBatchList", "async function _runBatch"),
        ("async function _runBatch", "out.querySelectorAll('[data-bc]')"),
    ]:
        start = dashboard_js.index(start_marker)
        end = dashboard_js.index(end_marker)
        block = dashboard_js[start:end]
        assert "style=" not in block

    assert "ocr-modal" in dashboard_js
    assert "ocr-batch-file" in dashboard_js
    assert "ocr-batch-card" in dashboard_js

    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    for class_name in ["dash-inline-016", "dash-inline-017", "dash-inline-018"]:
        assert class_name not in dashboard_html
        assert f".{class_name}" not in dashboard_css


def test_admin_management_views_do_not_reuse_generated_modal_classes():
    dashboard_css = (DASHBOARD / "enterprise-ui.css").read_text("utf-8")
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")

    for selector in [
        ".admin-action-btn",
        ".admin-stats-grid",
        ".admin-stat-card",
        ".admin-filter-row",
        ".admin-table-wrap",
        ".admin-table",
        ".admin-dialog",
        ".admin-dialog-panel",
        ".admin-form",
        ".admin-field",
    ]:
        assert selector in dashboard_css

    generated_modal_classes = [
        "dash-inline-069",
        "dash-inline-070",
        "dash-inline-071",
        "dash-inline-072",
        "dash-inline-073",
        "dash-inline-074",
        "dash-inline-075",
        "dash-inline-076",
        "dash-inline-077",
        "dash-inline-078",
        "dash-inline-079",
        "dash-inline-080",
        "dash-inline-081",
        "dash-inline-082",
        "dash-inline-083",
        "dash-inline-084",
        "dash-inline-085",
        "dash-inline-086",
        "dash-inline-087",
        "dash-inline-088",
        "dash-inline-089",
        "dash-inline-090",
        "dash-inline-091",
        "dash-inline-092",
        "dash-inline-093",
        "dash-inline-094",
    ]

    for view_id in ["risks", "certificates", "configs", "licenses", "budgets"]:
        start = dashboard_html.index(f'id="view-{view_id}"')
        section_start = dashboard_html.rfind("<section", 0, start)
        section_end = dashboard_html.index("</section>", start)
        section = dashboard_html[section_start:section_end]
        for class_name in generated_modal_classes:
            assert class_name not in section
        assert "admin-stats-grid" in section
        assert "admin-table" in section


def test_operations_admin_views_use_dedicated_spacing_classes():
    dashboard_html = (DASHBOARD / "index.html").read_text("utf-8")

    for view_id in ["deployments", "services", "problems"]:
        start = dashboard_html.index(f'id="view-{view_id}"')
        section_start = dashboard_html.rfind("<section", 0, start)
        section_end = dashboard_html.index("</section>", start)
        section = dashboard_html[section_start:section_end]

        assert "dash-inline-069" not in section
        assert "dash-inline-077" not in section
        assert "admin-stats-grid" in section
        assert "admin-select" in section
