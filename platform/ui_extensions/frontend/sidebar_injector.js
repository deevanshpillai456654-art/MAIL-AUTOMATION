
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
 * SidebarInjector — injects plugin-contributed sidebar items into the
 * existing core sidebar without modifying core HTML or JS files.
 *
 * Usage:
 *   import { SidebarInjector } from './sidebar_injector.js'
 *   const injector = new SidebarInjector('#sidebar-nav')
 *   injector.render(getRegistry().sidebar)
 *
 * The injector re-renders only the plugin section (<ul id="plugin-nav">)
 * and leaves core items untouched.
 */

import { onExtensionChange } from './plugin_sdk.js';

const PLUGIN_NAV_ID = 'plugin-sidebar-items';

export class SidebarInjector {
  constructor(sidebarSelector = '#sidebar-nav') {
    this._selector = sidebarSelector;
    this._items    = [];
    onExtensionChange(({ type, item }) => {
      if (type === 'sidebar' || type === 'deregister') this._render();
    });
  }

  mount(items) {
    this._items = items;
    this._render();
  }

  _render() {
    const sidebar = document.querySelector(this._selector);
    if (!sidebar) return;

    let container = document.getElementById(PLUGIN_NAV_ID);
    if (!container) {
      container = document.createElement('ul');
      container.id = PLUGIN_NAV_ID;
      container.className = 'plugin-nav-group';
      sidebar.appendChild(container);
    }
    window.setSafeHTML(container, this._items
      .sort((a, b) => (a.order || 100) - (b.order || 100))
      .map(item => `
        <li class="plugin-nav-item" data-plugin="${item.pluginId || item.plugin_id}">
          <a href="${item.route || '#'}">
            ${item.icon ? `<span class="nav-icon">${item.icon}</span>` : ''}
            <span class="nav-label">${item.label}</span>
          </a>
        </li>
      `).join(''));
  }
}
