"""
Structured troubleshooting knowledge base.

All issue flows, step definitions, SVG visuals and decision trees live here.
No AI inference is used inside this module — responses are deterministic and
cannot hallucinate.  The DiagnosticsEngine feeds runtime context that lets the
FlowEngine select the most relevant issue automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── colour palette matches the existing dashboard CSS tokens ─────────────────
_BG    = "#0f172a"
_CARD  = "#1e293b"
_BORD  = "#334155"
_BLUE  = "#3b82f6"
_GREEN = "#10b981"
_AMBER = "#f59e0b"
_RED   = "#ef4444"
_TEXT  = "#f1f5f9"
_MUTED = "#94a3b8"


# ── data model ───────────────────────────────────────────────────────────────

@dataclass
class Visual:
    type: str           # "svg" | "flow_diagram" | "callout"
    title: str
    content: str        # SVG markup or comma-sep flow node list
    annotation: str = ""


@dataclass
class ActionButton:
    action_id: str
    label: str
    style: str = "primary"          # "primary" | "danger" | "secondary"
    params: Dict[str, Any] = field(default_factory=dict)
    confirm_required: bool = True


@dataclass
class FlowStep:
    number: int
    title: str
    instruction: str
    detail: str = ""
    visual: Optional[Visual] = None
    action: Optional[ActionButton] = None
    expected_result: str = ""
    if_fails_issue: Optional[str] = None   # redirect to this issue on failure
    admin_only: bool = False


@dataclass
class IssueTemplate:
    id: str
    category: str
    title: str
    description: str
    severity: str                               # "info"|"low"|"moderate"|"high"|"critical"
    symptoms: List[str]
    diagnostic_signals: List[str]               # keys emitted by DiagnosticsEngine
    steps: List[FlowStep]
    visual_flow_nodes: List[str]
    related_issues: List[str]
    admin_steps: List[FlowStep] = field(default_factory=list)
    auto_detectable: bool = False
    tags: List[str] = field(default_factory=list)


# ── SVG visual helpers ────────────────────────────────────────────────────────

def _svg(title: str, body: str, w: int = 360, h: int = 160, annotation: str = "") -> Visual:
    content = (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="max-width:100%;border-radius:8px;background:{_BG}">'
        f'{body}'
        f'</svg>'
    )
    return Visual(type="svg", title=title, content=content, annotation=annotation)


def _flow(nodes: List[str], annotation: str = "") -> Visual:
    return Visual(type="flow_diagram", title="Resolution flow", content="|".join(nodes), annotation=annotation)


def _rect(x, y, w, h, fill, rx=4):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"/>'


def _text(x, y, msg, fill=_TEXT, size=11, weight="normal", anchor="start"):
    return f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-family="system-ui,sans-serif" font-weight="{weight}" text-anchor="{anchor}">{msg}</text>'


def _arrow_down(cx, y1, y2, colour=_AMBER):
    return (
        f'<line x1="{cx}" y1="{y1}" x2="{cx}" y2="{y2-8}" stroke="{colour}" stroke-width="2"/>'
        f'<polygon points="{cx-5},{y2-8} {cx+5},{y2-8} {cx},{y2}" fill="{colour}"/>'
    )


def _highlight_ring(x, y, w, h, colour=_AMBER):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="none" stroke="{colour}" stroke-width="2.5" stroke-dasharray="5,3"/>'


def _badge(x, y, label, colour=_AMBER, text_colour="#000"):
    tw = len(label) * 6.5 + 12
    return (
        f'<rect x="{x}" y="{y}" width="{tw}" height="18" rx="9" fill="{colour}"/>'
        f'<text x="{x + tw/2}" y="{y+12}" fill="{text_colour}" font-size="9" '
        f'font-family="system-ui,sans-serif" font-weight="700" text-anchor="middle">{label}</text>'
    )


# ── reusable dashboard-mockup fragments ───────────────────────────────────────

def _tray_icon_svg() -> Visual:
    body = (
        # desktop area
        _rect(0, 0, 360, 115, _CARD)
        # wallpaper hint
        + _rect(0, 0, 360, 100, "#0f172a")
        + _text(14, 22, "INTEMO", _BLUE, 12, "700")
        + _text(14, 38, "Workspace dashboard", _MUTED, 9)
        # taskbar
        + _rect(0, 100, 360, 32, "#020617")
        # tray area
        + _rect(248, 104, 100, 24, "#0f172a", 3)
        # clock
        + _text(296, 119, "09:41", _MUTED, 9)
        # INTEMO tray icon
        + _rect(254, 107, 18, 18, _BLUE, 4)
        + _text(260, 119, "I", _TEXT, 10, "700")
        # highlight ring with pulse
        + _highlight_ring(251, 104, 24, 24, _AMBER)
        # arrow pointing down to icon
        + _arrow_down(263, 80, 104, _AMBER)
        # callout label
        + _rect(195, 62, 135, 20, _AMBER, 10)
        + _text(263, 75, "Right-click INTEMO", "#000", 9, "600", "middle")
    )
    return _svg("Locate the INTEMO tray icon", body, annotation="Find the INTEMO icon (blue I) in the Windows system tray, bottom-right of your screen.")


def _dashboard_accounts_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 160, _BG)
        # sidebar
        + _rect(0, 0, 80, 160, _CARD)
        + _text(8, 24, "INTEMO", _BLUE, 10, "700")
        + _rect(4, 35, 72, 22, "#1e3a5f", 4)  # Accounts selected
        + _text(14, 50, "Accounts", _BLUE, 10, "600")
        + _text(14, 72, "Inbox", _MUTED, 10)
        + _text(14, 92, "Rules", _MUTED, 10)
        + _text(14, 112, "Analytics", _MUTED, 10)
        + _text(14, 132, "Settings", _MUTED, 10)
        # main area header
        + _text(96, 24, "Connected Accounts", _TEXT, 12, "600")
        # account card 1 - connected
        + _rect(92, 34, 260, 44, _CARD, 6)
        + _rect(100, 42, 28, 28, _GREEN, 14)
        + _text(114, 60, "G", _TEXT, 14, "700", "middle")
        + _text(136, 48, "user@gmail.com", _TEXT, 10, "500")
        + _text(136, 62, "Gmail  ●  Connected", _GREEN, 9)
        # account card 2 - error
        + _rect(92, 84, 260, 44, _CARD, 6)
        + _rect(100, 92, 28, 28, _RED, 14)
        + _text(114, 110, "O", _TEXT, 14, "700", "middle")
        + _text(136, 98, "user@outlook.com", _TEXT, 10, "500")
        + _text(136, 112, "Outlook  ●  Reconnect required", _RED, 9)
        + _highlight_ring(90, 82, 264, 48, _RED)
        + _badge(296, 86, "ERROR", _RED, _TEXT)
    )
    return _svg("Connected Accounts view", body, h=160, annotation="Open the Accounts section in the left sidebar. Accounts needing attention are highlighted in red.")


def _oauth_flow_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 160, _BG)
        # browser mockup
        + _rect(20, 10, 320, 30, _CARD, 6)
        + _rect(30, 16, 240, 18, "#020617", 3)
        + _text(150, 29, "accounts.google.com/oauth2/...", _MUTED, 8, "normal", "middle")
        + _rect(276, 17, 55, 16, _BLUE, 3)
        + _text(304, 28, "Secure", _TEXT, 8, "normal", "middle")
        # consent screen
        + _rect(20, 50, 320, 100, _CARD, 8)
        + _text(180, 72, "Google wants to access", _TEXT, 11, "600", "middle")
        + _text(180, 88, "your Gmail account", _MUTED, 10, "normal", "middle")
        # permission items
        + _rect(36, 96, 8, 8, _GREEN, 2) + _text(50, 104, "Read and manage emails", _MUTED, 9)
        + _rect(36, 112, 8, 8, _GREEN, 2) + _text(50, 120, "Send email on your behalf", _MUTED, 9)
        # allow button
        + _rect(220, 128, 100, 14, _BLUE, 7)
        + _text(270, 138, "Allow", _TEXT, 9, "600", "middle")
        + _highlight_ring(218, 126, 104, 18, _AMBER)
        + _badge(148, 126, "Click Allow", _AMBER)
    )
    return _svg("OAuth Consent Screen", body, h=160, annotation="Click 'Allow' on the Google/Microsoft consent page to grant INTEMO permission to access your mailbox.")


def _sync_status_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 130, _BG)
        # sync card
        + _rect(20, 15, 320, 100, _CARD, 8)
        + _text(36, 38, "Email Sync", _TEXT, 12, "600")
        + _text(36, 54, "Last synced: 2 minutes ago", _MUTED, 9)
        # progress bar
        + _rect(36, 64, 270, 8, "#020617", 4)
        + _rect(36, 64, 270, 8, _GREEN, 4)
        # status indicators
        + _rect(36, 82, 8, 8, _GREEN, 4)
        + _text(50, 90, "Gmail — 847 emails synced", _MUTED, 9)
        + _rect(36, 96, 8, 8, _AMBER, 4)
        + _text(50, 104, "Outlook — Syncing (page 3/12)...", _MUTED, 9)
        # retry button
        + _rect(286, 82, 46, 22, _BLUE, 11)
        + _text(309, 96, "Retry", _TEXT, 9, "600", "middle")
    )
    return _svg("Sync status panel", body, h=130, annotation="The sync progress bar shows live sync state. Green = healthy, Amber = in-progress, Red = error.")


def _extension_toolbar_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 130, _BG)
        # browser chrome bar
        + _rect(0, 0, 360, 40, "#020617")
        + _rect(14, 8, 200, 24, _CARD, 3)
        + _text(114, 24, "mail.google.com/mail/u/0/", _MUTED, 9, "normal", "middle")
        # extension area
        + _rect(260, 8, 88, 24, "#020617", 0)
        + _rect(268, 11, 18, 18, "#374151", 9)  # puzzle icon
        + _text(277, 23, "⊕", _MUTED, 10, "normal", "middle")
        + _rect(290, 11, 18, 18, _BLUE, 4)
        + _text(299, 23, "I", _TEXT, 10, "700", "middle")
        + _highlight_ring(287, 8, 24, 24, _AMBER)
        + _badge(238, 5, "INTEMO", _AMBER)
        + _arrow_down(299, 32, 50, _AMBER)
        # extension popup preview
        + _rect(240, 50, 100, 72, _CARD, 8)
        + _rect(248, 58, 84, 16, _BLUE, 3)
        + _text(290, 69, "INTEMO Active", _TEXT, 7, "600", "middle")
        + _rect(248, 80, 84, 10, "#020617", 3)
        + _rect(248, 80, 70, 10, _GREEN, 3)
        + _text(290, 88, "Bridge: Online", _MUTED, 7, "normal", "middle")
        + _text(290, 100, "Gmail scanning: ON", _GREEN, 7, "normal", "middle")
        + _text(290, 112, "Scam shield: Active", _GREEN, 7, "normal", "middle")
    )
    return _svg("Browser extension toolbar", body, h=130, annotation="Click the INTEMO icon (blue I) in the browser toolbar to check extension status.")


def _settings_advanced_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 150, _BG)
        # sidebar
        + _rect(0, 0, 90, 150, _CARD)
        + _text(8, 24, "Settings", _TEXT, 11, "700")
        + _text(8, 44, "General", _MUTED, 9)
        + _text(8, 60, "Accounts", _MUTED, 9)
        + _text(8, 76, "Sync", _MUTED, 9)
        + _text(8, 92, "Rules", _MUTED, 9)
        + _rect(4, 100, 82, 20, "#1e3a5f", 4)
        + _text(8, 113, "Advanced", _BLUE, 9, "600")
        + _text(8, 128, "About", _MUTED, 9)
        # main panel
        + _text(106, 24, "Advanced Settings", _TEXT, 12, "600")
        + _rect(100, 34, 250, 28, _CARD, 6)
        + _text(112, 52, "Clear sync cache", _TEXT, 10)
        + _rect(282, 39, 58, 18, "#374151", 9)
        + _text(311, 51, "Run", _MUTED, 9, "normal", "middle")
        + _rect(100, 68, 250, 28, _CARD, 6)
        + _text(112, 86, "Reset rules engine", _TEXT, 10)
        + _rect(100, 102, 250, 28, _CARD, 6)
        + _text(112, 120, "Diagnostics report", _TEXT, 10)
        + _highlight_ring(98, 32, 254, 32, _AMBER)
        + _badge(248, 24, "Go here first", _AMBER)
    )
    return _svg("Advanced Settings", body, h=150, annotation="Open Settings → Advanced to find sync cache management and diagnostics tools.")


def _job_queue_svg() -> Visual:
    body = (
        _rect(0, 0, 360, 150, _BG)
        + _text(20, 24, "Job Queue Status", _TEXT, 12, "600")
        # header row
        + _rect(16, 32, 328, 16, "#020617", 0)
        + _text(20, 43, "Job", _MUTED, 8) + _text(160, 43, "Status", _MUTED, 8) + _text(260, 43, "Age", _MUTED, 8)
        # rows
        + _rect(16, 50, 328, 20, _CARD, 3)
        + _text(20, 63, "sync_retry / outlook", _TEXT, 9) + _badge(150, 53, "leased", _AMBER) + _text(260, 63, "12 min", _MUTED, 8)
        + _rect(16, 72, 328, 20, _CARD, 3)
        + _text(20, 85, "sync_retry / gmail", _TEXT, 9) + _badge(150, 75, "pending", "#334155", _TEXT) + _text(260, 85, "1 min", _MUTED, 8)
        + _rect(16, 94, 328, 20, _CARD, 3)
        + _text(20, 107, "oauth_refresh / outlook", _TEXT, 9) + _badge(150, 97, "failed", _RED, _TEXT) + _text(260, 107, "8 min", _MUTED, 8)
        + _highlight_ring(14, 92, 332, 24, _RED)
        # action bar
        + _rect(16, 122, 150, 22, "#7c3aed", 11)
        + _text(91, 136, "Retry Failed Jobs", _TEXT, 9, "600", "middle")
        + _rect(176, 122, 150, 22, "#374151", 11)
        + _text(251, 136, "Clear Completed", _MUTED, 9, "normal", "middle")
    )
    return _svg("Job Queue", body, h=150, annotation="Failed jobs are shown in red. Use 'Retry Failed Jobs' to re-queue them automatically.")


# ── issue templates ───────────────────────────────────────────────────────────

def _build_issues() -> List[IssueTemplate]:
    issues: List[IssueTemplate] = []

    # ── 1. OAuth disconnected ─────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="oauth_disconnected",
        category="auth",
        title="Account Disconnected — Reconnect Required",
        description=(
            "Your email account lost its OAuth connection. This usually happens when a "
            "refresh token expires, the user revokes access in their Google/Microsoft "
            "account settings, or a password change invalidates the token."
        ),
        severity="high",
        symptoms=[
            "Account shows 'Reconnect required' in red",
            "Emails stopped syncing for this account",
            "Notifications about expired session",
            "OAuth error in diagnostics",
        ],
        diagnostic_signals=["disconnected_accounts", "oauth_errors"],
        auto_detectable=True,
        tags=["oauth", "auth", "gmail", "outlook", "sync"],
        visual_flow_nodes=[
            "Account disconnected",
            "Open Accounts panel",
            "Click Reconnect",
            "Approve OAuth consent",
            "Sync resumes automatically",
        ],
        related_issues=["oauth_permission_revoked", "sync_not_starting"],
        steps=[
            FlowStep(
                number=1,
                title="Open the Accounts panel",
                instruction="In the INTEMO dashboard, click **Accounts** in the left navigation sidebar.",
                detail="You will see all connected email accounts. Disconnected accounts appear with a red badge.",
                visual=_dashboard_accounts_svg(),
                expected_result="The Accounts list is visible with the disconnected account highlighted in red.",
            ),
            FlowStep(
                number=2,
                title="Click 'Reconnect' on the affected account",
                instruction="Find the account showing **'Reconnect required'** and click the **Reconnect** button next to it.",
                detail="This initiates a fresh OAuth flow. Your data is not deleted — INTEMO simply needs a new access token.",
                expected_result="A new browser window or tab opens pointing to Google/Microsoft's authentication page.",
                action=ActionButton(
                    action_id="reconnect_oauth",
                    label="Reconnect this account",
                    style="primary",
                    confirm_required=False,
                ),
            ),
            FlowStep(
                number=3,
                title="Approve the consent screen",
                instruction=(
                    "Sign in with your email account credentials on the provider's login page. "
                    "When the permissions screen appears, click **Allow** to grant INTEMO access."
                ),
                detail=(
                    "INTEMO requests the minimum required scopes: read/write mail access and "
                    "offline access (for background sync). No password is stored — only the OAuth token."
                ),
                visual=_oauth_flow_svg(),
                expected_result="You are redirected back to INTEMO and the account status changes to 'Connected'.",
            ),
            FlowStep(
                number=4,
                title="Verify sync resumes",
                instruction="After reconnecting, check the **Sync** panel. A new sync cycle should start within 30 seconds.",
                visual=_sync_status_svg(),
                expected_result="The account shows 'Connected' and sync activity begins.",
                if_fails_issue="sync_not_starting",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=5,
                title="[Admin] Inspect OAuth token state",
                instruction="Check the provider token health endpoint and review audit logs for token rotation history.",
                admin_only=True,
                action=ActionButton(
                    action_id="inspect_token_health",
                    label="Run token health check",
                    style="secondary",
                    confirm_required=False,
                ),
            ),
        ],
    ))

    # ── 2. Sync stuck / frozen ────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="sync_stuck",
        category="sync",
        title="Email Sync Stuck or Frozen",
        description=(
            "Sync appears to be running but makes no progress. Emails stop arriving "
            "despite the spinner being active. This can be caused by a stale job lease, "
            "provider throttling, or a network interruption mid-sync."
        ),
        severity="moderate",
        symptoms=[
            "Sync spinner running for more than 5 minutes",
            "No new emails arriving despite being expected",
            "Sync counter not incrementing",
            "Job queue shows 'leased' jobs older than 10 minutes",
        ],
        diagnostic_signals=["stale_sync_jobs", "sync_duration_exceeded"],
        auto_detectable=True,
        tags=["sync", "job_queue", "performance"],
        visual_flow_nodes=[
            "Sync frozen detected",
            "Check job queue for stale leases",
            "Retry stale jobs",
            "Monitor sync progress",
            "Verify emails arriving",
        ],
        related_issues=["oauth_disconnected", "backend_not_responding"],
        steps=[
            FlowStep(
                number=1,
                title="Check how long sync has been running",
                instruction=(
                    "Open **Settings → Advanced → Diagnostics** and look at the "
                    "'Sync Status' section. Note when the sync started."
                ),
                detail="A normal sync cycle takes 30 seconds to 3 minutes. Anything over 5 minutes is considered stuck.",
                visual=_sync_status_svg(),
                expected_result="You can see the sync start time and current status.",
            ),
            FlowStep(
                number=2,
                title="Restart the sync engine",
                instruction=(
                    "Click the **Restart Sync** button below, or use the tray menu: "
                    "right-click the INTEMO tray icon and select **Restart Sync Engine**."
                ),
                detail=(
                    "This cancels any stuck jobs and starts a fresh sync cycle. "
                    "No emails are deleted. Your sync checkpoint is preserved — "
                    "only emails from the last sync point onwards will be re-fetched."
                ),
                visual=_tray_icon_svg(),
                action=ActionButton(
                    action_id="restart_sync",
                    label="Restart sync engine",
                    style="primary",
                    confirm_required=True,
                ),
                expected_result="Sync restarts and begins making visible progress within 30 seconds.",
                if_fails_issue="backend_not_responding",
            ),
            FlowStep(
                number=3,
                title="Monitor the job queue",
                instruction="Check the job queue status. Any stale 'leased' jobs older than 5 minutes should now be cleared.",
                visual=_job_queue_svg(),
                action=ActionButton(
                    action_id="retry_stale_jobs",
                    label="Retry stale jobs",
                    style="secondary",
                    confirm_required=False,
                ),
                expected_result="Job queue shows 'pending' or 'completed' statuses — no stuck 'leased' entries.",
            ),
            FlowStep(
                number=4,
                title="Wait for sync to complete",
                instruction="Allow 2–5 minutes for sync to complete. Watch the sync counter increment in the status panel.",
                detail="Large mailboxes (>10,000 emails) may take longer on first sync. Subsequent syncs are incremental and fast.",
                expected_result="Sync completes and 'Last synced: X minutes ago' updates.",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=5,
                title="[Admin] Review scheduler task health",
                instruction="Check scheduler status for failed or missing tasks. Verify sync task next_run is set correctly.",
                admin_only=True,
                action=ActionButton(
                    action_id="check_scheduler_status",
                    label="View scheduler status",
                    style="secondary",
                    confirm_required=False,
                ),
            ),
        ],
    ))

    # ── 3. Sync not starting ──────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="sync_not_starting",
        category="sync",
        title="Sync Never Starts",
        description=(
            "Scheduled sync is not triggering at all. No sync activity appears in the "
            "status panel. This can indicate the scheduler is paused, sync is disabled "
            "in settings, or no accounts are connected."
        ),
        severity="moderate",
        symptoms=[
            "No sync activity visible",
            "Sync status shows 'Never synced'",
            "Scheduler task shows as disabled",
            "Sync interval shows 0 or empty",
        ],
        diagnostic_signals=["sync_task_disabled", "no_active_accounts"],
        auto_detectable=True,
        tags=["sync", "scheduler"],
        visual_flow_nodes=[
            "No sync activity",
            "Check scheduler settings",
            "Enable auto-sync",
            "Trigger manual sync",
            "Confirm sync starts",
        ],
        related_issues=["oauth_disconnected", "sync_stuck"],
        steps=[
            FlowStep(
                number=1,
                title="Check that auto-sync is enabled",
                instruction=(
                    "Open **Settings → Sync** and verify **Auto-sync** is toggled ON. "
                    "Also confirm the sync interval is set (recommended: every 30 seconds)."
                ),
                visual=_settings_advanced_svg(),
                expected_result="Auto-sync toggle is ON and interval shows 30s or 60s.",
            ),
            FlowStep(
                number=2,
                title="Confirm at least one account is connected",
                instruction="Open **Accounts** and verify at least one account shows a green 'Connected' status.",
                visual=_dashboard_accounts_svg(),
                expected_result="At least one account is connected and not showing an error.",
                if_fails_issue="oauth_disconnected",
            ),
            FlowStep(
                number=3,
                title="Trigger a manual sync",
                instruction="Click the **Sync Now** button in the dashboard topbar, or use the tray menu → **Sync Now**.",
                visual=_tray_icon_svg(),
                action=ActionButton(
                    action_id="trigger_manual_sync",
                    label="Trigger manual sync",
                    style="primary",
                    confirm_required=False,
                ),
                expected_result="Sync begins within 5 seconds and the status updates.",
            ),
        ],
    ))

    # ── 4. Extension not connecting ───────────────────────────────────────────
    issues.append(IssueTemplate(
        id="extension_not_connecting",
        category="extension",
        title="Browser Extension Not Connecting to INTEMO",
        description=(
            "The INTEMO browser extension cannot reach the local backend service. "
            "Extension shows an offline/disconnected state, scam detection badges "
            "are not appearing, and the extension popup shows a connection error."
        ),
        severity="moderate",
        symptoms=[
            "Extension icon shows grey or 'offline' badge",
            "Extension popup shows 'Cannot connect to INTEMO'",
            "No scam detection badges in Gmail/Outlook",
            "Extension popup shows bridge: offline",
        ],
        diagnostic_signals=["backend_unreachable_from_ext"],
        auto_detectable=False,
        tags=["extension", "browser", "bridge", "scam"],
        visual_flow_nodes=[
            "Extension offline",
            "Confirm INTEMO desktop is running",
            "Check extension is enabled",
            "Reload extension",
            "Verify bridge reconnects",
        ],
        related_issues=["backend_not_responding"],
        steps=[
            FlowStep(
                number=1,
                title="Confirm INTEMO desktop app is running",
                instruction=(
                    "Look for the INTEMO icon in your Windows system tray (bottom-right of screen). "
                    "If it is not there, launch INTEMO from your desktop or Start Menu."
                ),
                visual=_tray_icon_svg(),
                expected_result="INTEMO tray icon is visible and shows a blue 'I' icon.",
            ),
            FlowStep(
                number=2,
                title="Open the browser extension popup",
                instruction=(
                    "In your browser toolbar, click the INTEMO icon (blue I). "
                    "If you don't see it, click the puzzle-piece icon to find pinned extensions."
                ),
                visual=_extension_toolbar_svg(),
                expected_result="Extension popup opens showing bridge connection status.",
            ),
            FlowStep(
                number=3,
                title="Check the Bridge status",
                instruction=(
                    "The popup shows **Bridge: Online** or **Bridge: Offline**. "
                    "If offline, click **Reconnect** inside the popup. Wait 5 seconds."
                ),
                detail=(
                    "The extension communicates with INTEMO on port 4597 (localhost only). "
                    "If the backend service is running, the bridge reconnects automatically."
                ),
                expected_result="Bridge status changes to 'Online' within 5 seconds.",
                if_fails_issue="backend_not_responding",
            ),
            FlowStep(
                number=4,
                title="Reload the extension if still offline",
                instruction=(
                    "In Chrome: go to **chrome://extensions**, find INTEMO, and click **Reload**. "
                    "In Firefox: go to **about:addons**, find INTEMO, and click the reload button."
                ),
                detail="Reloading restarts the extension's background service worker and forces a new connection.",
                expected_result="Extension reloads and bridge status shows 'Online'.",
            ),
            FlowStep(
                number=5,
                title="Test scam detection is active",
                instruction="Open Gmail in your browser. Open any email. Look for the INTEMO analysis badge at the top of the email.",
                expected_result="A coloured badge (Safe / Suspicious / Scam) appears on the email. Scam shield is working.",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=6,
                title="[Admin] Check CORS and port binding",
                instruction="Verify backend is bound to 127.0.0.1:4597 and CORS allows the extension origin.",
                admin_only=True,
                action=ActionButton(
                    action_id="check_backend_binding",
                    label="Check backend binding",
                    style="secondary",
                    confirm_required=False,
                ),
            ),
        ],
    ))

    # ── 5. Wrong email category ───────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="wrong_category",
        category="classification",
        title="Emails Being Placed in the Wrong Category",
        description=(
            "INTEMO's AI classifier is placing emails into incorrect categories. "
            "Common causes: sender not in training data, ambiguous subject line, "
            "or the model needs feedback to improve for your mailbox."
        ),
        severity="low",
        symptoms=[
            "Promotional emails showing as 'Finance'",
            "Important client emails going to 'Newsletters'",
            "OTP codes not being detected",
            "Classification confidence shown as low (< 60%)",
        ],
        diagnostic_signals=["low_confidence_classifications"],
        auto_detectable=False,
        tags=["classification", "ai", "rules", "feedback"],
        visual_flow_nodes=[
            "Wrong category detected",
            "Use feedback button on email",
            "Create sender override rule",
            "Verify re-classification",
            "Check confidence improves",
        ],
        related_issues=["rules_not_applying"],
        steps=[
            FlowStep(
                number=1,
                title="Submit feedback on the misclassified email",
                instruction=(
                    "Open the misclassified email in INTEMO. At the top-right of the email view, "
                    "click the **feedback icon (thumbs down)** and select the correct category."
                ),
                detail=(
                    "Each feedback submission immediately updates the sender's classification profile. "
                    "After 3–5 corrections from the same sender, the AI adapts permanently."
                ),
                expected_result="Feedback is recorded and the email is re-categorised immediately.",
            ),
            FlowStep(
                number=2,
                title="Create a sender override rule",
                instruction=(
                    "For a permanent fix, create a rule: **Rules → New Rule → Condition: Sender is → "
                    "Action: Categorise as [correct category]**."
                ),
                detail="Sender override rules take priority over the AI classifier and cannot be overridden.",
                action=ActionButton(
                    action_id="open_rules_editor",
                    label="Open rules editor",
                    style="secondary",
                    confirm_required=False,
                ),
                expected_result="New rule saved. Future emails from this sender will be categorised correctly.",
            ),
            FlowStep(
                number=3,
                title="Re-classify existing emails",
                instruction=(
                    "After creating the rule, click **Apply rule to existing emails** "
                    "to fix all historically misclassified messages from this sender."
                ),
                expected_result="Existing emails are moved to the correct category within 30 seconds.",
            ),
        ],
    ))

    # ── 6. Rules not applying ─────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="rules_not_applying",
        category="classification",
        title="Automation Rules Not Running",
        description=(
            "Rules you created are not being applied to incoming emails. "
            "Emails matching rule conditions are not being moved, labelled, "
            "forwarded, or categorised as expected."
        ),
        severity="moderate",
        symptoms=[
            "New emails are not being auto-labelled",
            "Forwarding rules are not sending emails",
            "Category override rules being ignored",
            "Rule status shows 'inactive'",
        ],
        diagnostic_signals=["rule_execution_failures"],
        auto_detectable=False,
        tags=["rules", "automation"],
        visual_flow_nodes=[
            "Rules not executing",
            "Check rule is enabled",
            "Test rule conditions",
            "Re-apply to existing emails",
            "Monitor new emails",
        ],
        related_issues=["wrong_category", "oauth_disconnected"],
        steps=[
            FlowStep(
                number=1,
                title="Verify the rule is active",
                instruction="Open **Rules** in the sidebar. Find your rule and check that the toggle is **ON** (green).",
                detail="Disabled rules appear greyed out and are skipped during processing.",
                expected_result="Rule toggle is green (ON).",
            ),
            FlowStep(
                number=2,
                title="Check rule conditions are correct",
                instruction=(
                    "Click **Edit** on the rule. Verify the conditions are set correctly. "
                    "Example: 'Sender contains @newsletter.com' — check for typos."
                ),
                detail=(
                    "Common mistakes: using full email address in a 'contains' field instead of domain, "
                    "or case-sensitive text that doesn't match incoming emails."
                ),
                expected_result="Conditions look correct and match the expected email pattern.",
            ),
            FlowStep(
                number=3,
                title="Test rule against an existing email",
                instruction="Click **Test Rule** — this runs the rule against the last 20 emails to verify it would match correctly.",
                action=ActionButton(
                    action_id="reload_rules",
                    label="Reload rules engine",
                    style="secondary",
                    confirm_required=False,
                ),
                expected_result="Test results show matched emails. Rule logic confirmed.",
            ),
        ],
    ))

    # ── 7. Backend not responding ─────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="backend_not_responding",
        category="service",
        title="INTEMO Backend Service Not Responding",
        description=(
            "The INTEMO backend service is not reachable. The dashboard shows an error, "
            "sync stops, and the extension loses connectivity. The service may have crashed "
            "or the port may be in use by another application."
        ),
        severity="critical",
        symptoms=[
            "Dashboard shows 'Cannot connect to service'",
            "INTEMO tray icon is missing or grey",
            "All sync stopped across all accounts",
            "Health check returns error",
        ],
        diagnostic_signals=["backend_health_failed"],
        auto_detectable=True,
        tags=["backend", "service", "critical"],
        visual_flow_nodes=[
            "Backend unreachable",
            "Check tray icon status",
            "Restart INTEMO service",
            "Check port availability",
            "Verify backend starts",
        ],
        related_issues=["extension_not_connecting", "sync_stuck"],
        steps=[
            FlowStep(
                number=1,
                title="Check the INTEMO tray icon",
                instruction="Look for the INTEMO icon in the Windows system tray. A grey or missing icon means the service is not running.",
                visual=_tray_icon_svg(),
                expected_result="Icon is visible. If missing, proceed to step 2.",
            ),
            FlowStep(
                number=2,
                title="Restart the INTEMO service",
                instruction=(
                    "If the tray icon is visible: right-click → **Restart Service**. "
                    "If no tray icon: open INTEMO from your Start Menu or Desktop shortcut."
                ),
                detail=(
                    "Restarting the service does not delete any data. All emails, rules, and "
                    "settings are preserved. Sync will resume from the last checkpoint."
                ),
                expected_result="INTEMO loads and the tray icon reappears in blue within 15 seconds.",
            ),
            FlowStep(
                number=3,
                title="Verify the backend is healthy",
                instruction="Once restarted, wait 10 seconds then check the health status in the dashboard topbar.",
                action=ActionButton(
                    action_id="run_health_check",
                    label="Run health check now",
                    style="primary",
                    confirm_required=False,
                ),
                expected_result="Health check shows all components green.",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=4,
                title="[Admin] Check port 4597 availability",
                instruction=(
                    "Run: `netstat -an | findstr 4597` to check if another process is holding the port. "
                    "If so, identify and stop the conflicting process."
                ),
                admin_only=True,
            ),
            FlowStep(
                number=5,
                title="[Admin] Review crash logs",
                instruction="Check backend/data/logs/service.log for stack traces and error context from the last crash.",
                admin_only=True,
                action=ActionButton(
                    action_id="fetch_recent_logs",
                    label="View recent log entries",
                    style="secondary",
                    confirm_required=False,
                ),
            ),
        ],
    ))

    # ── 8. High resource usage ────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="high_resource_usage",
        category="performance",
        title="High CPU or Memory Usage",
        description=(
            "INTEMO is consuming more system resources than expected. This can happen "
            "during initial mailbox import, heavy AI classification, or if a sync cycle "
            "is looping due to a provider issue."
        ),
        severity="moderate",
        symptoms=[
            "CPU usage above 50% sustained",
            "Memory usage above 500 MB",
            "Computer fan running loudly while INTEMO is open",
            "Dashboard response feels slow or laggy",
        ],
        diagnostic_signals=["high_cpu", "high_memory"],
        auto_detectable=True,
        tags=["performance", "resources", "memory", "cpu"],
        visual_flow_nodes=[
            "High resource use detected",
            "Identify heavy operation",
            "Pause non-critical sync",
            "Run DB maintenance",
            "Monitor recovery",
        ],
        related_issues=["sync_stuck", "database_locked"],
        steps=[
            FlowStep(
                number=1,
                title="Check what INTEMO is doing",
                instruction="Open the health panel (diagnostics icon in topbar). Check CPU, memory, and active job count.",
                action=ActionButton(
                    action_id="run_health_check",
                    label="Open diagnostics",
                    style="secondary",
                    confirm_required=False,
                ),
                expected_result="You can see what operation is using resources (sync, AI processing, etc.).",
            ),
            FlowStep(
                number=2,
                title="Run database maintenance",
                instruction=(
                    "Click **Run DB Maintenance** below. This compacts the WAL file and removes "
                    "old job records that may be consuming memory."
                ),
                detail=(
                    "INTEMO uses SQLite WAL mode. Over time the WAL file can grow if not checkpointed. "
                    "Maintenance reclaims disk I/O and can reduce memory pressure."
                ),
                action=ActionButton(
                    action_id="run_db_maintenance",
                    label="Run DB maintenance",
                    style="secondary",
                    confirm_required=True,
                ),
                expected_result="WAL checkpoint completes and old records are pruned.",
            ),
            FlowStep(
                number=3,
                title="Reduce sync frequency temporarily",
                instruction=(
                    "If resource usage is sustained, go to **Settings → Sync** and change the "
                    "sync interval to **60 seconds** instead of 30 seconds."
                ),
                expected_result="CPU usage drops within 2 minutes as sync cycles become less frequent.",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=4,
                title="[Admin] Review AI inference load",
                instruction="Check AI metrics endpoint for inference queue depth and latency. High queue = model under load.",
                admin_only=True,
            ),
        ],
    ))

    # ── 9. Database locked ────────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="database_locked",
        category="service",
        title="Database Locked — Operations Failing",
        description=(
            "INTEMO's SQLite database is locked, causing sync, classification and "
            "rule operations to fail. This usually occurs if the previous process "
            "crashed mid-write or an antivirus is scanning the database file."
        ),
        severity="high",
        symptoms=[
            "Errors containing 'database is locked'",
            "Sync failing immediately after start",
            "Rules not saving",
            "Dashboard showing persistent errors",
        ],
        diagnostic_signals=["database_locked"],
        auto_detectable=True,
        tags=["database", "sqlite", "wal"],
        visual_flow_nodes=[
            "DB locked error",
            "Close any file-locking tools",
            "Run WAL checkpoint",
            "Restart service",
            "Verify DB is healthy",
        ],
        related_issues=["backend_not_responding"],
        steps=[
            FlowStep(
                number=1,
                title="Ensure no other process is accessing the DB",
                instruction=(
                    "Check that antivirus software is not scanning the INTEMO data folder. "
                    "Add **backend/data/** to your antivirus exclusion list if possible."
                ),
                detail="Real-time antivirus scanning of active SQLite WAL files is a common cause of lock contention.",
                expected_result="Antivirus exclusion confirmed. No other process accessing the DB file.",
            ),
            FlowStep(
                number=2,
                title="Run a WAL checkpoint to clear the lock",
                instruction="Click the button below to run a PASSIVE WAL checkpoint. This safely flushes pending writes.",
                action=ActionButton(
                    action_id="run_db_maintenance",
                    label="Run WAL checkpoint",
                    style="primary",
                    confirm_required=False,
                ),
                expected_result="WAL checkpoint completes without errors. DB lock is released.",
            ),
            FlowStep(
                number=3,
                title="Restart INTEMO if the lock persists",
                instruction="If the database is still locked after the checkpoint, restart INTEMO from the tray menu.",
                visual=_tray_icon_svg(),
                expected_result="INTEMO restarts cleanly and opens the DB with a fresh connection pool.",
            ),
        ],
    ))

    # ── 10. First-time setup ──────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="first_time_setup",
        category="onboarding",
        title="First-Time Setup Guide",
        description=(
            "Welcome to INTEMO. This guided walkthrough will connect your first email "
            "account, configure basic AI sorting, and verify sync is working correctly."
        ),
        severity="info",
        symptoms=["First launch", "No accounts connected", "Setup not completed"],
        diagnostic_signals=["no_accounts"],
        auto_detectable=True,
        tags=["onboarding", "setup", "welcome"],
        visual_flow_nodes=[
            "Launch INTEMO",
            "Connect email account",
            "Choose OAuth (recommended)",
            "Approve consent",
            "First sync runs",
            "AI sorting begins",
        ],
        related_issues=["oauth_disconnected", "sync_not_starting"],
        steps=[
            FlowStep(
                number=1,
                title="Open the Account Connection wizard",
                instruction="In the left sidebar, click **Accounts → Add Account**. Select your email provider.",
                visual=_dashboard_accounts_svg(),
                expected_result="Provider selection screen appears.",
            ),
            FlowStep(
                number=2,
                title="Choose OAuth (recommended) or App Password",
                instruction=(
                    "Select **Sign in with Google** / **Sign in with Microsoft** for OAuth. "
                    "This is the most secure method — no password is stored."
                    "\n\nIf your provider does not support OAuth, use **App Password** mode."
                ),
                detail="OAuth tokens can be revoked at any time from your provider's security settings without changing your password.",
                expected_result="OAuth consent page opens in your browser.",
            ),
            FlowStep(
                number=3,
                title="Approve the OAuth consent",
                instruction="Sign in and click **Allow** on the Google or Microsoft consent screen.",
                visual=_oauth_flow_svg(),
                expected_result="You are redirected back to INTEMO and your account shows 'Connected'.",
            ),
            FlowStep(
                number=4,
                title="Wait for the initial sync to complete",
                instruction=(
                    "INTEMO will now import your emails. First-time sync may take 2–10 minutes "
                    "depending on mailbox size. You can use INTEMO while it runs in the background."
                ),
                visual=_sync_status_svg(),
                expected_result="Sync counter increments. Emails begin appearing in INTEMO.",
            ),
            FlowStep(
                number=5,
                title="Review AI category assignments",
                instruction=(
                    "Once sync completes, open **Inbox**. INTEMO will have sorted your emails "
                    "into categories (Finance, Clients, Promotions, etc.). "
                    "Use the feedback button to correct any misclassifications."
                ),
                expected_result="Emails are organised by category. AI sorting is active.",
            ),
        ],
    ))

    # ── 11. Sync missing emails ───────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="sync_missing_emails",
        category="sync",
        title="Emails Missing After Sync",
        description=(
            "Sync completed but expected emails are not visible in INTEMO. "
            "The emails exist in your mailbox provider but have not been imported. "
            "Common causes: provider API pagination limit hit, date filter active, "
            "or sync checkpoint set beyond the missing email date."
        ),
        severity="moderate",
        symptoms=[
            "Specific emails visible in Gmail/Outlook but not in INTEMO",
            "INTEMO shows fewer emails than expected",
            "Emails before a certain date are missing",
            "Sync shows completed but email count seems low",
        ],
        diagnostic_signals=[],
        auto_detectable=False,
        tags=["sync", "gmail", "outlook", "missing"],
        visual_flow_nodes=[
            "Emails missing in INTEMO",
            "Check sync date range",
            "Reset sync checkpoint",
            "Re-sync affected account",
            "Verify emails appear",
        ],
        related_issues=["sync_stuck", "oauth_disconnected"],
        steps=[
            FlowStep(
                number=1,
                title="Check if the missing email is within the sync date range",
                instruction=(
                    "INTEMO syncs emails from your connected date onwards. "
                    "Open **Settings → Accounts → [account name]** and check the "
                    "'Sync from date' setting. Emails before this date are intentionally excluded."
                ),
                detail="By default INTEMO syncs the last 30 days on first connect. Older emails are not imported unless the range is extended.",
                visual=_settings_advanced_svg(),
                expected_result="You can see the sync start date. If the missing email is older, extend the date range.",
            ),
            FlowStep(
                number=2,
                title="Trigger a full re-sync of the account",
                instruction=(
                    "Go to **Accounts**, find the affected account, and click **Re-sync**. "
                    "This resets the sync checkpoint and re-fetches all emails within the configured date range."
                ),
                detail=(
                    "Re-syncing does not delete existing emails. It will import any previously "
                    "missed emails and skip duplicates automatically."
                ),
                visual=_dashboard_accounts_svg(),
                action=ActionButton(
                    action_id="restart_sync",
                    label="Trigger re-sync",
                    style="primary",
                    confirm_required=True,
                ),
                expected_result="Sync starts and previously missing emails begin appearing within 2–5 minutes.",
            ),
            FlowStep(
                number=3,
                title="Check that the email is not filtered by a rule",
                instruction=(
                    "Open **Rules** and look for any rules that might be deleting, archiving "
                    "or hiding emails from the sender in question."
                ),
                expected_result="No rules are incorrectly filtering the missing emails.",
                if_fails_issue="rules_not_applying",
            ),
        ],
    ))

    # ── 12. Extension scam badges not showing ────────────────────────────────
    issues.append(IssueTemplate(
        id="extension_no_badges",
        category="extension",
        title="Scam Detection Badges Not Appearing on Emails",
        description=(
            "The INTEMO browser extension is installed and connected but scam "
            "analysis badges are not visible on emails in Gmail or Outlook. "
            "The extension may need a page reload or the content script "
            "may have failed to inject."
        ),
        severity="low",
        symptoms=[
            "INTEMO extension shows 'Online' but no badges in Gmail",
            "Email view opens but no INTEMO analysis card appears",
            "Extension popup shows scanning is ON but nothing visible on emails",
            "Only some emails show badges but not others",
        ],
        diagnostic_signals=[],
        auto_detectable=False,
        tags=["extension", "scam", "badges", "gmail", "browser"],
        visual_flow_nodes=[
            "Badges missing",
            "Reload Gmail/Outlook tab",
            "Check extension permissions",
            "Verify content script active",
            "Badges appear",
        ],
        related_issues=["extension_not_connecting"],
        steps=[
            FlowStep(
                number=1,
                title="Reload the Gmail or Outlook tab",
                instruction=(
                    "Press **Ctrl+R** (or Cmd+R on Mac) on the Gmail or Outlook web tab. "
                    "Wait for the page to fully load, then open an email."
                ),
                detail="Content scripts are injected on page load. If Gmail was already open when the extension was installed or updated, a reload is required.",
                expected_result="After reloading, INTEMO badges appear at the top of opened emails.",
            ),
            FlowStep(
                number=2,
                title="Verify the extension has permission for the current site",
                instruction=(
                    "Click the INTEMO extension icon in your browser toolbar. "
                    "The popup should show **Gmail scanning: ON** (or Outlook). "
                    "If it shows OFF, click to enable it for this site."
                ),
                visual=_extension_toolbar_svg(),
                expected_result="Popup shows scanning enabled for mail.google.com or outlook.live.com.",
            ),
            FlowStep(
                number=3,
                title="Check for browser extension conflicts",
                instruction=(
                    "Other email-related extensions can sometimes block INTEMO's content script. "
                    "Temporarily disable other Gmail/Outlook extensions to test."
                ),
                detail="Common conflicts: ad blockers with aggressive filtering, other email organiser extensions, corporate security extensions.",
                expected_result="Disabling conflicting extensions restores badge visibility.",
            ),
            FlowStep(
                number=4,
                title="Reload the INTEMO extension itself",
                instruction=(
                    "In Chrome: go to **chrome://extensions**, find INTEMO, and click **Reload**. "
                    "Then reload your Gmail/Outlook tab."
                ),
                expected_result="Extension reloads fresh. Badges appear on the next email you open.",
                if_fails_issue="extension_not_connecting",
            ),
        ],
    ))

    # ── 13. Update stuck ──────────────────────────────────────────────────────
    issues.append(IssueTemplate(
        id="update_stuck",
        category="service",
        title="INTEMO Update Not Completing",
        description=(
            "An INTEMO update is available or was started but has not completed. "
            "The update may be stuck downloading, waiting for user confirmation, "
            "or blocked by antivirus software."
        ),
        severity="low",
        symptoms=[
            "Update notification appears repeatedly without completing",
            "Update download progress bar is stuck",
            "INTEMO version has not changed after a reported update",
            "Update failed silently",
        ],
        diagnostic_signals=[],
        auto_detectable=False,
        tags=["update", "installer"],
        visual_flow_nodes=[
            "Update not completing",
            "Check network connection",
            "Allow antivirus exception",
            "Restart and re-check update",
            "Manual update if needed",
        ],
        related_issues=["backend_not_responding"],
        steps=[
            FlowStep(
                number=1,
                title="Check your internet connection",
                instruction=(
                    "Updates are downloaded from the INTEMO update server. "
                    "Ensure you have an active internet connection and no VPN or firewall "
                    "is blocking outbound HTTPS traffic."
                ),
                expected_result="Internet is accessible. You can load websites normally.",
            ),
            FlowStep(
                number=2,
                title="Add INTEMO to your antivirus exclusion list",
                instruction=(
                    "Antivirus software sometimes blocks update downloads. "
                    "Add the INTEMO installation folder to your antivirus exclusion list, "
                    "then retry the update."
                ),
                detail=(
                    "Default INTEMO install location: C:\\Program Files\\INTEMO\\ "
                    "or wherever you installed INTEMO on first setup."
                ),
                expected_result="Antivirus exclusion added. Update download can proceed.",
            ),
            FlowStep(
                number=3,
                title="Restart INTEMO and check for updates again",
                instruction=(
                    "Right-click the INTEMO tray icon and select **Restart Service**. "
                    "After restart, right-click the tray icon again and select "
                    "**Check for Updates**."
                ),
                visual=_tray_icon_svg(),
                expected_result="INTEMO restarts and the update check runs cleanly.",
            ),
            FlowStep(
                number=4,
                title="Apply the update when prompted",
                instruction=(
                    "When the update is ready, a notification will appear asking you to "
                    "restart INTEMO to apply it. Click **Restart Now** to complete the update."
                ),
                detail="INTEMO never applies updates silently — you always confirm first. Your data is preserved.",
                expected_result="INTEMO restarts with the new version. Check Settings → About to confirm version number.",
            ),
        ],
        admin_steps=[
            FlowStep(
                number=5,
                title="[Admin] Check update signing key configuration",
                instruction="Verify that the update manifest signing key is configured and the update URL is reachable.",
                admin_only=True,
                action=ActionButton(
                    action_id="check_backend_binding",
                    label="Check service config",
                    style="secondary",
                    confirm_required=False,
                ),
            ),
        ],
    ))

    return issues


# ── singleton ─────────────────────────────────────────────────────────────────

class KnowledgeBase:
    def __init__(self) -> None:
        self._issues: Dict[str, IssueTemplate] = {}
        for issue in _build_issues():
            self._issues[issue.id] = issue

    # ── lookups ────────────────────────────────────────────────────────────────

    def get_issue(self, issue_id: str) -> Optional[IssueTemplate]:
        return self._issues.get(issue_id)

    def all_issues(self) -> List[IssueTemplate]:
        return list(self._issues.values())

    def issues_by_category(self, category: str) -> List[IssueTemplate]:
        return [i for i in self._issues.values() if i.category == category]

    def categories(self) -> List[str]:
        seen: Dict[str, None] = {}
        for i in self._issues.values():
            seen[i.category] = None
        return list(seen)

    def auto_detectable(self) -> List[IssueTemplate]:
        return [i for i in self._issues.values() if i.auto_detectable]

    def search(self, query: str) -> List[IssueTemplate]:
        q = query.lower()
        results = []
        for issue in self._issues.values():
            score = 0
            if q in issue.title.lower():
                score += 3
            if q in issue.description.lower():
                score += 2
            if any(q in s.lower() for s in issue.symptoms):
                score += 2
            if any(q in t.lower() for t in issue.tags):
                score += 1
            if score:
                results.append((score, issue))
        results.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in results]

    def to_index(self) -> List[Dict[str, Any]]:
        """Lightweight index for the frontend category browser."""
        return [
            {
                "id": i.id,
                "category": i.category,
                "title": i.title,
                "description": i.description[:120] + "…",
                "severity": i.severity,
                "symptoms": i.symptoms[:3],
                "auto_detectable": i.auto_detectable,
                "tags": i.tags,
                "step_count": len(i.steps),
            }
            for i in self._issues.values()
        ]


_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
