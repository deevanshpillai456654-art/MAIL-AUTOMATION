
window.setSafeHTML = function(el, html) {
  if (!el) return;
  if (typeof html !== 'string') {
    el.textContent = String(html);
    return;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const badTags = doc.querySelectorAll('script, iframe, object, embed, form, base, applet, meta, link');
  badTags.forEach(n => n.remove());
  const all = doc.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    const node = all[i];
    for (let j = node.attributes.length - 1; j >= 0; j--) {
      const attr = node.attributes[j];
      if (attr.name.toLowerCase().startsWith('on') || attr.name.toLowerCase() === 'javascript:') {
        node.removeAttribute(attr.name);
      }
    }
  }
  el.replaceChildren(...doc.body.childNodes);
};

/**
 * WidgetLoader — dynamically loads and mounts plugin-contributed widgets
 * into a dashboard grid without modifying core dashboard code.
 *
 * Widgets declare a JS component path; the loader uses dynamic import()
 * to fetch the component module and render it into a grid slot.
 *
 * Usage:
 *   import { WidgetLoader } from './widget_loader.js'
 *   const loader = new WidgetLoader('#dashboard-grid')
 *   await loader.mount(getRegistry().widgets)
 */

import { onExtensionChange } from './plugin_sdk.js';

export class WidgetLoader {
  constructor(gridSelector = '#dashboard-grid') {
    this._selector  = gridSelector;
    this._mounted   = new Map();   // widget_id → DOM element
    onExtensionChange(async ({ type }) => {
      if (type === 'widget' || type === 'deregister') await this._sync();
    });
  }

  async mount(widgets) {
    for (const w of widgets) {
      await this._mountWidget(w);
    }
  }

  async _sync() {
    // Called on registry change — remount any new widgets
    const { getRegistry } = await import('./plugin_sdk.js');
    const widgets = getRegistry().widgets;
    for (const w of widgets) {
      if (!this._mounted.has(w.widget_id || w.widgetId)) {
        await this._mountWidget(w);
      }
    }
  }

  async _mountWidget(widgetDef) {
    const id = widgetDef.widget_id || widgetDef.widgetId;
    if (this._mounted.has(id)) return;

    const grid = document.querySelector(this._selector);
    if (!grid) return;

    const slot = document.createElement('div');
    slot.className  = 'plugin-widget-slot';
    slot.id         = `widget-${id}`;
    slot.dataset.plugin = widgetDef.plugin_id || widgetDef.pluginId;
    slot.style.gridColumn = `span ${widgetDef.min_width || widgetDef.minWidth || 3}`;

    try {
      const mod = await import(widgetDef.component);
      if (mod.default && typeof mod.default.render === 'function') {
        mod.default.render(slot, widgetDef.config || {});
      } else if (typeof mod.mount === 'function') {
        mod.mount(slot, widgetDef.config || {});
      } else {
        window.setSafeHTML(slot, `<div class="plugin-widget-placeholder">${widgetDef.label}</div>`);
      }
    } catch (err) {
      window.setSafeHTML(
        slot,
        `<div class="plugin-widget-error">⚠ ${widgetDef.label} failed to load</div>`
      );
    }

    grid.appendChild(slot);
    this._mounted.set(id, slot);
  }

  unmount(widgetId) {
    const el = this._mounted.get(widgetId);
    if (el) { el.remove(); this._mounted.delete(widgetId); }
  }
}
