/**
 * PluginFrontendSDK — JavaScript SDK for plugin-contributed UI components.
 *
 * Loaded once by the host shell.  Plugins import from this module to
 * register sidebar items, widgets, and routes without touching core files.
 *
 * Usage (inside a plugin's frontend entry):
 *
 *   import { registerSidebarItem, registerWidget, registerRoute } from '/platform/ui/plugin_sdk.js'
 *
 *   registerSidebarItem({
 *     pluginId: 'salesforce',
 *     itemId:   'sf-contacts',
 *     label:    'SF Contacts',
 *     icon:     '👥',
 *     route:    '/plugins/salesforce/contacts',
 *     order:    20,
 *   })
 */

const _registry = {
  sidebar: [],
  widgets: [],
  routes:  [],
  _listeners: [],
};

function _notify(type, item) {
  _registry._listeners.forEach(fn => {
    try { fn({ type, item }); } catch (_) {}
  });
}

/** Register a sidebar navigation item contributed by a plugin. */
export function registerSidebarItem(item) {
  _registry.sidebar.push(item);
  _notify('sidebar', item);
}

/** Register a dashboard widget contributed by a plugin. */
export function registerWidget(widget) {
  _registry.widgets.push(widget);
  _notify('widget', widget);
}

/** Register a client-side route contributed by a plugin. */
export function registerRoute(route) {
  _registry.routes.push(route);
  _notify('route', route);
}

/** Subscribe to registry change events. */
export function onExtensionChange(fn) {
  _registry._listeners.push(fn);
}

/** Read-only snapshot of all registered extensions. */
export function getRegistry() {
  return {
    sidebar: [..._registry.sidebar],
    widgets: [..._registry.widgets],
    routes:  [..._registry.routes],
  };
}

/** Remove all contributions from a specific plugin (hot-reload / uninstall). */
export function deregisterPlugin(pluginId) {
  _registry.sidebar = _registry.sidebar.filter(i => i.pluginId !== pluginId);
  _registry.widgets = _registry.widgets.filter(w => w.pluginId !== pluginId);
  _registry.routes  = _registry.routes.filter(r  => r.pluginId !== pluginId);
  _notify('deregister', { pluginId });
}
