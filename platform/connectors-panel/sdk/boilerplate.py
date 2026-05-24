"""
MailPilot Plugin Scaffold Generator

Generates a new plugin directory with all required files.

Usage:
    python -m platform.connectors-panel.sdk.boilerplate --name my_connector --category communication --type oauth
    python -m platform.connectors-panel.sdk.boilerplate --help
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

PLUGIN_TYPES = ("base", "connector", "oauth", "webhook")
CATEGORIES = ("communication", "erp", "crm", "tracking", "ocr", "search", "ai", "ecommerce", "webhook", "internal")


def _plugin_json_template(name: str, category: str, plugin_type: str) -> dict:
    base = {
        "name": name,
        "version": "1.0.0",
        "type": "connector",
        "category": category,
        "description": f"{name.replace('_', ' ').title()} connector plugin",
        "author": "MailPilot",
        "enabled": False,
        "multiTenant": True,
        "supports_oauth": plugin_type == "oauth",
        "supports_api_key": plugin_type in ("connector", "webhook"),
        "supports_webhook": plugin_type == "webhook",
        "queue_enabled": True,
        "permissions": [],
        "events": [],
        "config_schema": {},
    }
    if plugin_type == "oauth":
        base["oauth_scopes"] = []
        base["permissions"] = ["data.read", "data.write"]
    elif plugin_type == "webhook":
        base["webhook_events"] = []
        base["permissions"] = ["webhooks.receive", "events.publish"]
    else:
        base["permissions"] = ["data.read"]
    return base


def _module_py_template(name: str, plugin_type: str) -> str:
    class_name = "".join(w.title() for w in name.split("_")) + "Connector"
    sdk_import_path = "platform.connectors_panel.sdk.plugin_sdk"

    if plugin_type == "oauth":
        base_class = "OAuthPlugin"
        extra_imports = ""
        extra_methods = '''
    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        """Build the OAuth authorization URL."""
        import os
        from urllib.parse import urlencode
        client_id = os.environ.get(f"{self.plugin_id.upper()}_CLIENT_ID", "")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.get_scopes()),
            "state": tenant_id,
        }
        return f"https://example.com/oauth/authorize?{urlencode(params)}"

    def exchange_code(self, tenant_id: str, code: str) -> dict:
        """Exchange authorization code for tokens."""
        # IMPLEMENT: replace the example.com endpoint and credentials with the real provider token URL
        import httpx, os
        response = httpx.post(
            "https://example.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": os.environ.get(f"{self.plugin_id.upper()}_CLIENT_ID", ""),
                "client_secret": os.environ.get(f"{self.plugin_id.upper()}_CLIENT_SECRET", ""),
            },
        )
        response.raise_for_status()
        return response.json()

    def get_scopes(self) -> list[str]:
        """Return required OAuth scopes."""
        return []
'''
    elif plugin_type == "webhook":
        base_class = "WebhookPlugin"
        extra_imports = "import hmac\nimport hashlib\n"
        extra_methods = '''
    def handle_webhook(self, payload: dict, headers: dict, tenant_id: str) -> dict:
        """Process inbound webhook payload."""
        # IMPLEMENT: parse payload and publish domain events via self._publish_event()
        events_published = 0
        return {
            "processed": True,
            "events_published": events_published,
        }

    def validate_signature(self, payload: bytes, headers: dict) -> bool:
        """Validate webhook HMAC signature."""
        import os
        from ..shared.utils import verify_hmac
        secret = os.environ.get(f"{self.plugin_id.upper()}_WEBHOOK_SECRET", "")
        if not secret:
            return True  # Skip validation if no secret configured
        signature = headers.get("X-Hub-Signature-256", "")
        return verify_hmac(secret, payload, signature)
'''
    elif plugin_type == "connector":
        base_class = "ConnectorPlugin"
        extra_imports = ""
        extra_methods = '''
    def test_connection(self, tenant_id: str, config: dict) -> bool:
        """Test API connectivity."""
        try:
            import httpx, os
            api_key = config.get("api_key") or os.environ.get(f"{self.plugin_id.upper()}_API_KEY", "")
            response = httpx.get(
                "https://api.example.com/ping",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            return response.is_success
        except Exception:
            return False
'''
    else:
        base_class = "BasePlugin"
        extra_imports = ""
        extra_methods = ""

    return f'''"""
{name.replace("_", " ").title()} Plugin Module

Auto-generated by MailPilot Plugin Scaffold Generator.
Customize this file to implement your plugin logic.
"""
from __future__ import annotations

{extra_imports}from typing import Any, Optional
from {sdk_import_path} import {base_class}, ConnectorSyncResult


class {class_name}({base_class}):
    """
    {name.replace("_", " ").title()} connector plugin.
    Generated by the MailPilot Plugin SDK boilerplate generator.
    """

    @property
    def plugin_id(self) -> str:
        return "{name}"

    @property
    def name(self) -> str:
        return "{name.replace("_", " ").title()}"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "{base_class.lower() if plugin_type == "base" else "communication"}"

    def on_install(self, tenant_id: str, config: dict[str, Any]) -> bool:
        """One-time setup when installed for a tenant."""
        self._log("INFO", f"Installing {{self.name}} for tenant {{tenant_id}}", tenant_id)
        # IMPLEMENT: perform one-time tenant setup (e.g. create DB tables, register webhooks)
        return True

    def on_uninstall(self, tenant_id: str) -> bool:
        """Cleanup when uninstalled."""
        self._log("INFO", f"Uninstalling {{self.name}} for tenant {{tenant_id}}", tenant_id)
        return True

    def on_enable(self, tenant_id: str) -> bool:
        self._log("INFO", f"Enabling {{self.name}} for tenant {{tenant_id}}", tenant_id)
        return True

    def on_disable(self, tenant_id: str) -> bool:
        self._log("INFO", f"Disabling {{self.name}} for tenant {{tenant_id}}", tenant_id)
        return True

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        """Return health status."""
        return {{"status": "ok", "message": f"{{self.name}} is running", "tenant_id": tenant_id}}

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch data from the external service."""
        # IMPLEMENT: call the external API and return a list of normalized record dicts
        return []

    def get_permissions(self) -> list[str]:
        return []

    def get_events(self) -> list[str]:
        return []

    def get_config_schema(self) -> dict[str, Any]:
        return {{
            "type": "object",
            "required": [],
            "properties": {{
                # IMPLEMENT: declare required config fields, e.g.:
                # "api_key": {{"type": "string", "description": "API Key"}}
            }},
        }}
{extra_methods}
'''


def _permissions_json_template(name: str) -> dict:
    return {
        "plugin_id": name,
        "permissions": [
            {
                "name": "data.read",
                "description": f"Read data from {name.replace('_', ' ').title()}",
                "level": "read",
            }
        ],
    }


def _events_json_template(name: str, category: str) -> dict:
    prefix = category.split(".")[0]
    return {
        "plugin_id": name,
        "published_events": [
            {
                "event_type": f"{prefix}.data.synced",
                "description": f"Fired when {name.replace('_', ' ')} data is synced",
                "payload_schema": {
                    "type": "object",
                    "properties": {
                        "record_count": {"type": "integer"},
                        "tenant_id": {"type": "string"},
                    },
                },
            }
        ],
        "subscribed_events": [],
    }


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_plugin(
    name: str,
    category: str,
    plugin_type: str,
    output_dir: Optional[str] = None,
) -> Path:
    """
    Generate a new plugin scaffold directory.

    Args:
        name:       Plugin name (snake_case, e.g. my_crm)
        category:   Plugin category (must be in CATEGORIES)
        plugin_type: Plugin type: base | connector | oauth | webhook
        output_dir: Directory to create the plugin in.
                    Defaults to current working directory.

    Returns:
        Path to the created plugin directory.
    """
    if category not in CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {', '.join(CATEGORIES)}")
    if plugin_type not in PLUGIN_TYPES:
        raise ValueError(f"Invalid type '{plugin_type}'. Must be one of: {', '.join(PLUGIN_TYPES)}")

    # Sanitise name
    safe_name = name.strip().lower().replace(" ", "_").replace("-", "_")
    if not safe_name.isidentifier():
        raise ValueError(f"Plugin name '{safe_name}' is not a valid Python identifier")

    base_dir = Path(output_dir or os.getcwd())
    plugin_dir = base_dir / safe_name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # __init__.py
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    # plugin.json
    manifest = _plugin_json_template(safe_name, category, plugin_type)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # module.py
    module_src = _module_py_template(safe_name, plugin_type)
    (plugin_dir / "module.py").write_text(module_src, encoding="utf-8")

    # permissions.json
    perms = _permissions_json_template(safe_name)
    (plugin_dir / "permissions.json").write_text(
        json.dumps(perms, indent=2), encoding="utf-8"
    )

    # events.json
    events = _events_json_template(safe_name, category)
    (plugin_dir / "events.json").write_text(
        json.dumps(events, indent=2), encoding="utf-8"
    )

    print(f"Plugin scaffold created at: {plugin_dir}")
    print(f"  Files created:")
    for f in sorted(plugin_dir.iterdir()):
        print(f"    - {f.name}")
    return plugin_dir


def print_usage() -> None:
    print("""
MailPilot Plugin Scaffold Generator
====================================

Usage:
    python -m platform.connectors_panel.sdk.boilerplate --name <name> --category <category> --type <type> [--output <dir>]

Arguments:
    --name      Plugin name in snake_case (e.g. my_crm_connector)
    --category  One of: communication, erp, crm, tracking, ocr, search, ai, ecommerce, webhook, internal
    --type      One of: base, connector, oauth, webhook
    --output    Output directory (default: current working directory)

Examples:
    python -m platform.connectors_panel.sdk.boilerplate --name hubspot_crm --category crm --type oauth
    python -m platform.connectors_panel.sdk.boilerplate --name fedex_tracker --category tracking --type webhook --output ./plugins
""")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="boilerplate",
        description="MailPilot Plugin Scaffold Generator",
    )
    parser.add_argument("--name", required=True, help="Plugin name (snake_case)")
    parser.add_argument(
        "--category",
        required=True,
        choices=CATEGORIES,
        help="Plugin category",
    )
    parser.add_argument(
        "--type",
        dest="plugin_type",
        required=True,
        choices=PLUGIN_TYPES,
        help="Plugin type: base | connector | oauth | webhook",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: current working directory)",
    )
    parser.add_argument("--usage", action="store_true", help="Show usage information")

    args = parser.parse_args()

    if args.usage:
        print_usage()
        sys.exit(0)

    try:
        generate_plugin(args.name, args.category, args.plugin_type, args.output)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
