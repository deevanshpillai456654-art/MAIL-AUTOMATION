#!/usr/bin/env python3
"""Validate and package browser extensions for customer installation."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "browser-extension-packages"
OUTLOOK_ADDIN = ROOT / "outlook-addin"
EXTENSIONS = {
    "chrome": ROOT / "extensions" / "chrome",
    "edge": ROOT / "extensions" / "edge",
    "firefox": ROOT / "extensions" / "firefox",
    "brave": ROOT / "extensions" / "brave",
    "opera": ROOT / "extensions" / "opera",
    "safari": ROOT / "extensions" / "safari",
    "gmail-chrome": ROOT / "gmail-extension",
}

REQUIRED_MANIFEST_KEYS = {"manifest_version", "name", "version"}
REQUIRED_FILES = {"manifest.json", "popup.html", "popup.js"}


class AssetReferenceParser(HTMLParser):
    """Collect local asset references that must survive extension packaging."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "link" and values.get("href"):
            rel = (values.get("rel") or "").lower()
            if any(kind in rel for kind in ("stylesheet", "icon", "manifest")):
                self.refs.append(("href", values["href"]))
        elif tag == "script" and values.get("src"):
            self.refs.append(("src", values["src"]))
        elif tag in {"img", "source"} and values.get("src"):
            self.refs.append(("src", values["src"]))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_external_reference(ref: str) -> bool:
    ref = ref.strip().lower()
    return (
        not ref
        or ref.startswith(("#", "data:", "mailto:", "javascript:", "chrome:", "moz-extension:"))
        or "://" in ref
    )


def resolve_packaged_asset(page: Path, base: Path, ref: str) -> Path | None:
    if is_external_reference(ref):
        return None
    clean_ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not clean_ref:
        return None
    if clean_ref.startswith("/"):
        return base / clean_ref.lstrip("/")
    return page.parent / clean_ref


def validate_html_asset_references(name: str, page: Path, base: Path) -> None:
    if not page.exists():
        raise FileNotFoundError(f"{name}: missing HTML page {page.relative_to(base)}")

    parser = AssetReferenceParser()
    parser.feed(page.read_text(encoding="utf-8", errors="ignore"))
    missing = []
    for attr, ref in parser.refs:
        asset_path = resolve_packaged_asset(page, base, ref)
        if asset_path is not None and not asset_path.exists():
            missing.append(f"{attr}={ref}")
    if missing:
        rel_page = page.relative_to(base).as_posix()
        raise FileNotFoundError(f"{name}: {rel_page} references missing assets {missing}")


def validate_extension(name: str, path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{name}: missing folder {path}")
    for rel in REQUIRED_FILES:
        if not (path / rel).exists():
            raise FileNotFoundError(f"{name}: missing {rel}")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST_KEYS - set(manifest))
    if missing:
        raise ValueError(f"{name}: manifest missing {missing}")
    if manifest.get("manifest_version") != 3:
        raise ValueError(f"{name}: only Manifest V3 is expected")
    options_page = manifest.get("options_page")
    if not options_page:
        raise ValueError(f"{name}: missing browser options_page for settings panel")
    if not (path / options_page).exists():
        raise FileNotFoundError(f"{name}: missing options page {options_page}")
    if not (path / "options.js").exists():
        raise FileNotFoundError(f"{name}: missing options.js settings controller")
    options_text = (path / options_page).read_text(encoding="utf-8", errors="ignore").lower()
    if "<script>" in options_text or "javascript:" in options_text:
        raise ValueError(f"{name}: options page has inline script blocked by Manifest V3 CSP")
    popup_page = manifest.get("action", {}).get("default_popup", "popup.html")
    validate_html_asset_references(name, path / popup_page, path)
    validate_html_asset_references(name, path / options_page, path)
    for icon in (manifest.get("icons") or {}).values():
        if not (path / icon).exists():
            raise FileNotFoundError(f"{name}: missing icon {icon}")
    background = manifest.get("background") or {}
    if background.get("service_worker") and not (path / background["service_worker"]).exists():
        raise FileNotFoundError(f"{name}: missing background service worker {background['service_worker']}")
    for content in manifest.get("content_scripts", []):
        for js in content.get("js", []):
            if not (path / js).exists():
                raise FileNotFoundError(f"{name}: missing content script {js}")
        for css in content.get("css", []):
            if not (path / css).exists():
                raise FileNotFoundError(f"{name}: missing content stylesheet {css}")
    return manifest


def xml_text(root: ET.Element, tag: str) -> str:
    for element in root.iter():
        if local_name(element.tag) == tag and element.text:
            return element.text.strip()
    return ""


def display_name(root: ET.Element) -> str:
    for element in root.iter():
        if local_name(element.tag) == "DisplayName":
            for child in element:
                if local_name(child.tag) == "DefaultValue" and child.text:
                    return child.text.strip()
    return xml_text(root, "ProviderName")


def validate_outlook_addin(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"outlook-addin: missing folder {path}")

    for rel in ("manifest.xml", "taskpane.html", "taskpane.js"):
        if not (path / rel).exists():
            raise FileNotFoundError(f"outlook-addin: missing {rel}")
    for icon in ("icon16.png", "icon32.png", "icon48.png", "icon128.png"):
        if not (path / "icons" / icon).exists():
            raise FileNotFoundError(f"outlook-addin: missing icons/{icon}")

    manifest_path = path / "manifest.xml"
    root = ET.parse(manifest_path).getroot()
    if local_name(root.tag) != "OfficeApp":
        raise ValueError("outlook-addin: manifest root must be OfficeApp")

    version = xml_text(root, "Version")
    name = display_name(root)
    if not version:
        raise ValueError("outlook-addin: manifest missing Version")
    if not name:
        raise ValueError("outlook-addin: manifest missing DisplayName")

    manifest_text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    if "taskpane.html" not in manifest_text:
        raise ValueError("outlook-addin: manifest must reference taskpane.html")
    if "icons/icon32.png" not in manifest_text or "icons/icon128.png" not in manifest_text:
        raise ValueError("outlook-addin: manifest must reference required icon URLs")

    validate_html_asset_references("outlook-addin", path / "taskpane.html", path)

    local_refs = sorted(set(re.findall(r"https?://(?:127\.0\.0\.1|localhost):\d+/([^\"'<\s]+)", manifest_text)))
    required_refs = {"taskpane.html", "icons/icon16.png", "icons/icon32.png", "icons/icon128.png"}
    missing = [ref for ref in required_refs if ref not in local_refs]
    if missing:
        raise ValueError(f"outlook-addin: manifest missing local references {missing}")

    return {
        "name": name,
        "version": version,
        "package_type": "office-addin",
    }


def zip_dir(source: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(source.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                archive.write(file, file.relative_to(source).as_posix())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, path in EXTENSIONS.items():
        manifest = validate_extension(name, path)
        target = OUT / f"ai-email-organizer-{name}-extension-v{manifest['version']}.zip"
        zip_dir(path, target)
        summary.append({
            "browser": name,
            "name": manifest["name"],
            "version": manifest["version"],
            "package": target.name,
        })
    outlook = validate_outlook_addin(OUTLOOK_ADDIN)
    outlook_target = OUT / f"ai-email-organizer-outlook-addin-v{outlook['version']}.zip"
    zip_dir(OUTLOOK_ADDIN, outlook_target)
    summary.append({
        "browser": "outlook-addin",
        "name": outlook["name"],
        "version": outlook["version"],
        "package": outlook_target.name,
        "package_type": outlook["package_type"],
        "manual_install": "Extract the ZIP and sideload manifest.xml as a custom Outlook add-in.",
    })
    (OUT / "manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    readme = [
        "# INTEMO Extension Packages",
        "",
        "Packaged extension ZIPs are provided for Chrome, Edge, Brave, Opera, Firefox, Safari-compatible source, Gmail-only Chrome use, and the Outlook add-in.",
        "",
        "## Install for Chromium browsers",
        "1. Open chrome://extensions, edge://extensions, brave://extensions, or opera://extensions.",
        "2. Enable Developer mode.",
        "3. Extract the matching ZIP and choose Load unpacked.",
        "4. Select the extracted extension folder.",
        "",
        "## Install for Firefox",
        "1. Open about:debugging#/runtime/this-firefox.",
        "2. Choose Load Temporary Add-on.",
        "3. Select manifest.json from the extracted Firefox ZIP.",
        "",
        "## Install for Outlook",
        "1. Extract the Outlook add-in ZIP.",
        "2. In Outlook, open add-ins and choose the custom add-in / sideload option.",
        "3. Select manifest.xml from the extracted Outlook add-in folder.",
        "4. Keep the local INTEMO service running at http://127.0.0.1:4597.",
        "",
        "The extension only talks to the local service at http://127.0.0.1:4597 or http://localhost:4597. It does not store OAuth refresh tokens or mailbox passwords.",
    ]
    (OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
