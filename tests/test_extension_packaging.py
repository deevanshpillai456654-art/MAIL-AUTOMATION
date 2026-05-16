import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "package_browser_extensions.py"


def load_packager():
    spec = importlib.util.spec_from_file_location("package_browser_extensions", PACKAGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packager_validates_extension_html_asset_links():
    packager = load_packager()

    assert hasattr(packager, "validate_html_asset_references")
    for name, path in packager.EXTENSIONS.items():
        manifest = packager.validate_extension(name, path)
        popup = manifest.get("action", {}).get("default_popup", "popup.html")
        packager.validate_html_asset_references(name, path / popup, path)
        packager.validate_html_asset_references(name, path / manifest["options_page"], path)


def test_packager_includes_outlook_addin_for_manual_install():
    packager = load_packager()

    assert hasattr(packager, "OUTLOOK_ADDIN")
    summary = packager.validate_outlook_addin(packager.OUTLOOK_ADDIN)

    assert summary["name"] == "AI Email Organizer"
    assert summary["version"]
    assert (packager.OUTLOOK_ADDIN / "manifest.xml").is_file()
    assert (packager.OUTLOOK_ADDIN / "taskpane.html").is_file()
    assert (packager.OUTLOOK_ADDIN / "taskpane.js").is_file()
    for icon in ["icon16.png", "icon32.png", "icon128.png"]:
        assert (packager.OUTLOOK_ADDIN / "icons" / icon).is_file()


def test_extension_runtimes_self_heal_without_browser_api(tmp_path):
    packager = load_packager()
    smoke = tmp_path / "runtime_smoke.js"
    smoke.write_text(
        """
const fs = require('fs');
const vm = require('vm');
const runtimePath = process.argv[2];
const code = fs.readFileSync(runtimePath, 'utf8');
const context = {
  console,
  URL,
  setTimeout,
  clearTimeout,
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  crypto: { randomUUID: () => 'runtime-smoke-id' }
};
vm.createContext(context);
vm.runInContext(code, context, { filename: runtimePath });
(async () => {
  const runtime = context.AIOExtensionRuntime;
  if (!runtime) throw new Error('runtime_not_exported');
  await runtime.saveSettings({
    apiOrigin: 'http://localhost:4510',
    autoDiscover: false,
    autoClassify: false,
    threatThreshold: 72
  });
  const settings = await runtime.getSettings();
  const healing = runtime.selfHealingStatus();
  if (settings.apiOrigin !== 'http://localhost:4510') throw new Error('fallback_storage_lost_origin');
  if (settings.autoDiscover !== false) throw new Error('fallback_storage_lost_boolean');
  if (settings.threatThreshold !== 72) throw new Error('fallback_storage_lost_number');
  if (!healing.fallbackBrowserApiActive) throw new Error('fallback_browser_api_not_active');
  if (!healing.events.some(event => event.action === 'extension_browser_api_fallback')) {
    throw new Error('fallback_event_not_recorded');
  }
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
""",
        encoding="utf-8",
    )

    for name, path in packager.EXTENSIONS.items():
        runtime = path / "extension_runtime.js"
        assert runtime.is_file(), name
        subprocess.run(["node", str(smoke), str(runtime)], check=True, cwd=ROOT)
