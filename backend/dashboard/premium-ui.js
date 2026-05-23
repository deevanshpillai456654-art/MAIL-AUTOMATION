// AI36 premium frontend runtime: command shortcuts, skeletons, AI assistant, accessible micro-interactions.
(() => {
  'use strict';

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

  const $ = (id) => document.getElementById(id);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const theme = 'light'; // default — enterprise-ui.js restores saved theme from localStorage

  function addHero() {
    const dashboard = $('view-dashboard');
    if (!dashboard || dashboard.querySelector('.ai34-hero')) return;
    const hero = document.createElement('section');
    hero.className = 'ai34-hero';
    window.setSafeHTML(
      hero,
      `<div><span class="ai34-pill">✦ AI-native command center</span><h2>Operate every inbox from one premium workspace.</h2><p>Universal OAuth, app-password onboarding, AI sorting, automation, analytics, and sync diagnostics now share one calm desktop-class interface.</p><div class="ai34-hero-actions"><button class="btn btn-primary" type="button" data-open-view="accounts">Connect provider</button><button class="btn" type="button" id="ai34OpenAssistant">Ask AI assistant</button><button class="btn" type="button" id="ai34OpenPalette">Open command palette</button></div><div class="ai34-trust-row"><span class="ai34-pill">OAuth-first</span><span class="ai34-pill">No password conflict</span><span class="ai34-pill">Offline-ready</span><span class="ai34-pill">WCAG focus states</span></div></div><aside class="ai34-pulse-card" aria-label="Live production pulse"><b>Workspace pulse</b><div class="ai34-orbit"><span><strong>Auth health</strong><em>Protected</em></span><span><strong>Sync recovery</strong><em>Online</em></span><span><strong>AI routing</strong><em>Ready</em></span><span><strong>Token vault</strong><em>Encrypted</em></span></div></aside>`
    );
    dashboard.insertBefore(hero, dashboard.firstElementChild);
  }
  function addOnboardingProgress() {
    const form = $('accountForm');
    if (!form || form.querySelector('.ai34-onboarding-progress')) return;
    const progress = document.createElement('div');
    progress.className = 'ai34-onboarding-progress';
    window.setSafeHTML(
      progress,
      `<div class="ai34-progress-track" aria-label="Onboarding progress"><span id="ai34ProgressFill"></span></div><div class="ai34-step-grid"><div class="ai34-step active" data-step="email">1. Detect provider</div><div class="ai34-step" data-step="auth">2. Choose OAuth or app password</div><div class="ai34-step" data-step="validate">3. Validate securely</div><div class="ai34-step" data-step="sync">4. Start sync + AI</div></div>`
    );
    form.insertBefore(progress, form.firstElementChild);
    const update = () => {
      const email = form.email?.value || '';
      const method = $('connectionMethod')?.value || 'app_password';
      const pct = email.includes('@') ? (method === 'oauth' ? 58 : 48) : 16;
      const fill = $('ai34ProgressFill');
      if (fill) fill.style.setProperty('--progress', `${pct}%`);
      $$('.ai34-step', form).forEach((step, index) => step.classList.toggle('active', index === 0 || (email.includes('@') && index < 2) || (method === 'oauth' && index < 3)));
    };
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    update();
  }
  function addEmptyStates() {
    [['accountList','Connected mailboxes appear here after OAuth/app-password onboarding.'],['activityList','Workflow activity appears after sync, AI routing, or rule execution.'],['notificationList','Provider and sync alerts will appear here when action is needed.']].forEach(([id,msg]) => {
      const el = $(id);
      if (el && !el.children.length) window.setSafeHTML(el, `<div class="ai34-empty-state"><b>Nothing yet</b>${msg}</div>`);
    });
  }
  function addAssistant() {
    if ($('ai34AssistantButton')) return;
    const btn = document.createElement('button');
    btn.className = 'ai34-ai-button';
    btn.id = 'ai34AssistantButton';
    btn.type = 'button';
    btn.title = 'Open AI Support Assistant';
    btn.textContent = 'AI Assist';
    document.body.appendChild(btn);

    function openAssistant(issueId) {
      const base = '/assistant';
      const params = new URLSearchParams();
      if (localStorage.getItem('ai34-admin') === '1') params.set('mode', 'admin');
      if (issueId) params.set('issue', issueId);
      const qs = params.toString();
      window.location.href = base + (qs ? '?' + qs : '');
    }

    btn.addEventListener('click', () => openAssistant());
    $('ai34OpenAssistant')?.addEventListener('click', () => openAssistant());
  }
  function bindPremiumShortcuts() {
    $('ai34OpenPalette')?.addEventListener('click', () => $('commandPaletteBtn')?.click());
    document.addEventListener('keydown', (event) => {
      if (event.altKey && event.key.toLowerCase() === 'a') { event.preventDefault(); $('ai34AssistantButton')?.click(); }
    });
  }
  function init() {
    addHero();
    addOnboardingProgress();
    addEmptyStates();
    addAssistant();
    bindPremiumShortcuts();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
