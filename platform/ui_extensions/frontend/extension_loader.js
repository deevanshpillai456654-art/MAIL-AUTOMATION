/**
 * ExtensionLoader — fetches the UI manifest from the backend and seeds the
 * client-side PluginSDK registry.
 *
 * Call loadExtensions() once after the user authenticates. The loader
 * polls for manifest updates when hot-reload is enabled.
 */

import { registerSidebarItem, registerWidget, registerRoute, deregisterPlugin } from './plugin_sdk.js';

const MANIFEST_URL = '/platform/ui/manifest';
const POLL_INTERVAL_MS = 30_000;

let _pollTimer = null;
let _lastEtag  = null;

/**
 * Fetch the current UI manifest from the backend and register all
 * contributions into the client-side registry.
 */
export async function loadExtensions() {
  try {
    const headers = {};
    if (_lastEtag) headers['If-None-Match'] = _lastEtag;

    const resp = await fetch(MANIFEST_URL, { headers });
    if (resp.status === 304) return;  // nothing changed
    if (!resp.ok) {
      return;
    }

    _lastEtag = resp.headers.get('etag') || null;
    const manifest = await resp.json();
    applyManifest(manifest);
  } catch (err) {}
}

/** Apply a manifest object into the client registry (idempotent). */
export function applyManifest(manifest) {
  (manifest.sidebar || []).forEach(item => registerSidebarItem(item));
  (manifest.widgets || []).forEach(w    => registerWidget(w));
  (manifest.routes  || []).forEach(r    => registerRoute(r));
}

/** Start polling for manifest changes. */
export function startPolling(intervalMs = POLL_INTERVAL_MS) {
  if (_pollTimer) return;
  _pollTimer = setInterval(loadExtensions, intervalMs);
}

/** Stop polling. */
export function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

/** Remove all contributions for a plugin by ID (used after uninstall). */
export function unloadPlugin(pluginId) {
  deregisterPlugin(pluginId);
}
