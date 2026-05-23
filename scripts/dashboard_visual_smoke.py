#!/usr/bin/env python3
"""Capture visual smoke screenshots for the INTEMO dashboard."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import URLError
from urllib.request import urlopen

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:4597/dashboard"
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "dashboard-visual-smoke"
SERVICE_STARTUP_WAIT_SECONDS = 90
# Visual smoke runs in offline and packaged Windows environments where Chromium's
# font readiness promise can remain pending even after the app is fully rendered.
os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")
SERVICE_START_COMMAND = (
    sys.executable,
    "-m",
    "uvicorn",
    "backend.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "4597",
    "--lifespan",
    "off",
)


@dataclass(frozen=True)
class DashboardView:
    name: str
    action: str
    selector: str = ""
    ready_selector: str = ".view.active"


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int


@dataclass(frozen=True)
class CaptureRecord:
    view: str
    viewport: str
    path: Path


def primary_nav_selector(view_name: str) -> str:
    return f'.main-nav > button.nav-btn[data-view="{view_name}"]'


DASHBOARD_VIEWS: tuple[DashboardView, ...] = (
    DashboardView("dashboard", "initial", ready_selector="#view-dashboard.active"),
    DashboardView("accounts", "nav", primary_nav_selector("accounts"), "#view-accounts.active"),
    DashboardView("inbox", "nav", primary_nav_selector("inbox"), "#view-inbox.active"),
    DashboardView("scam", "filter", '[data-filter="scam"]', "#view-inbox.active"),
    DashboardView("ai", "nav", primary_nav_selector("ai"), "#view-ai.active"),
    DashboardView("automations", "nav", primary_nav_selector("automations"), "#view-automations.active"),
    DashboardView("templates", "nav", primary_nav_selector("templates"), "#view-templates.active"),
    DashboardView("reports", "nav", primary_nav_selector("reports"), "#view-reports.active"),
    DashboardView("connectors", "nav", primary_nav_selector("connectors"), "#view-connectors.active"),
    DashboardView("workflows", "nav", primary_nav_selector("workflows"), "#view-workflows.active"),
    DashboardView("agents", "nav", primary_nav_selector("agents"), "#view-agents.active"),
    DashboardView("command", "nav", primary_nav_selector("command"), "#view-command.active"),
    DashboardView("admin", "nav", primary_nav_selector("admin"), "#view-admin.active"),
    DashboardView("settings", "nav", primary_nav_selector("settings"), "#view-settings.active"),
)


DEFAULT_VIEWPORTS: tuple[Viewport, ...] = (
    Viewport("desktop 1440x900", 1440, 900),
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "item"


def screenshot_path(output_dir: Path, view_name: str, viewport_name: str) -> Path:
    return output_dir / _slug(viewport_name) / f"{_slug(view_name)}.png"


def load_sync_playwright():
    try:
        module = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for dashboard visual smoke screenshots. "
            "Install it with `pip install playwright` and then run "
            "`python -m playwright install chromium`."
        ) from exc
    return module.sync_playwright


def service_available(base_url: str, timeout: float = 2.0) -> bool:
    health_url = base_url.split("/dashboard", 1)[0].rstrip("/") + "/api/v1/health"
    try:
        with urlopen(health_url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, URLError):
        return False


def start_service_if_needed(base_url: str) -> subprocess.Popen | None:
    if service_available(base_url):
        return None

    process = subprocess.Popen(
        list(SERVICE_START_COMMAND),
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        close_fds=True,
    )
    for _ in range(SERVICE_STARTUP_WAIT_SECONDS):
        if service_available(base_url, timeout=1.0):
            return process
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise RuntimeError(f"Dashboard service exited during startup.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        time.sleep(1)

    process.terminate()
    raise RuntimeError(f"Dashboard service did not become healthy within {SERVICE_STARTUP_WAIT_SECONDS} seconds.")


def wait_for_dashboard_idle(page, timeout_ms: int) -> None:
    page.wait_for_selector(".app-shell", timeout=timeout_ms)
    page.wait_for_timeout(300)


def open_view(page, view: DashboardView, timeout_ms: int) -> None:
    if view.action == "initial":
        page.wait_for_selector(view.ready_selector, timeout=timeout_ms)
        return
    if view.name == "scam":
        page.locator(primary_nav_selector("inbox")).click()
        page.wait_for_selector("#view-inbox.active", timeout=timeout_ms)
    page.locator(view.selector).click()
    page.wait_for_selector(view.ready_selector, timeout=timeout_ms)
    page.wait_for_timeout(350)


def capture_screenshots(
    base_url: str = DEFAULT_BASE_URL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    views: Sequence[DashboardView] = DASHBOARD_VIEWS,
    viewports: Sequence[Viewport] = DEFAULT_VIEWPORTS,
    timeout_ms: int = 15_000,
) -> list[CaptureRecord]:
    sync_playwright = load_sync_playwright()
    records: list[CaptureRecord] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for viewport in viewports:
                context = browser.new_context(
                    viewport={"width": viewport.width, "height": viewport.height},
                    device_scale_factor=1,
                )
                # Set system_admin role before any page JS runs so role-gated nav items
                # (command, admin) are visible during smoke capture.
                context.add_init_script("localStorage.setItem('ai36NavRole', 'system_admin')")
                try:
                    page = context.new_page()
                    page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    wait_for_dashboard_idle(page, timeout_ms)
                    for view in views:
                        open_view(page, view, timeout_ms)
                        path = screenshot_path(output_dir, view.name, viewport.name)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(path), full_page=True)
                        validate_screenshot(path)
                        records.append(CaptureRecord(view.name, viewport.name, path.relative_to(output_dir)))
                finally:
                    context.close()
        finally:
            browser.close()

    write_manifest(output_dir, base_url, records)
    return records


def validate_screenshot(path: Path, min_width: int = 320, min_height: int = 240, min_size: int = 4096) -> None:
    if not path.is_file():
        raise RuntimeError(f"Screenshot missing: {path}")
    if path.stat().st_size < min_size:
        raise RuntimeError(f"Screenshot too small: {path}")

    with Image.open(path).convert("RGB") as image:
        width, height = image.size
        if width < min_width or height < min_height:
            raise RuntimeError(f"Screenshot dimensions too small: {path} ({width}x{height})")
        extrema = image.getextrema()
        if all(low == high for low, high in extrema):
            raise RuntimeError(f"Screenshot appears blank: {path}")


def write_manifest(output_dir: Path, base_url: str, records: Iterable[CaptureRecord]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "manifest.json"
    payload = {
        "base_url": base_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "screenshots": [
            {"view": record.view, "viewport": record.viewport, "path": str(record.path).replace("\\", "/")}
            for record in records
        ],
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def parse_viewports(values: Sequence[str]) -> list[Viewport]:
    viewports: list[Viewport] = []
    for value in values:
        match = re.fullmatch(r"([A-Za-z0-9_-]+):(\d+)x(\d+)", value)
        if not match:
            raise ValueError(f"Invalid viewport '{value}'. Use name:WIDTHxHEIGHT, for example desktop:1440x900.")
        name, width, height = match.groups()
        viewports.append(Viewport(name, int(width), int(height)))
    return viewports


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture dashboard visual smoke screenshots.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-start-service", action="store_true", help="Do not start the local service if it is offline.")
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    parser.add_argument(
        "--viewport",
        action="append",
        default=[],
        help="Viewport as name:WIDTHxHEIGHT. Can be passed multiple times.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    service_process = None
    try:
        if not args.no_start_service:
            service_process = start_service_if_needed(args.base_url)
        elif not service_available(args.base_url):
            raise RuntimeError(f"Dashboard service is not reachable at {args.base_url}.")

        viewports = parse_viewports(args.viewport) if args.viewport else list(DEFAULT_VIEWPORTS)
        records = capture_screenshots(
            base_url=args.base_url,
            output_dir=args.output_dir,
            viewports=viewports,
            timeout_ms=args.timeout_ms,
        )
        print(f"Captured {len(records)} dashboard screenshot(s) in {args.output_dir}")
        return 0
    except Exception as exc:
        print(f"Dashboard visual smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if service_process is not None:
            service_process.terminate()
            try:
                service_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                service_process.kill()
                service_process.wait(timeout=8)


if __name__ == "__main__":
    raise SystemExit(main())
