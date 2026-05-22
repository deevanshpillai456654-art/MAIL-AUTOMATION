# INTEMO Platform — Comprehensive Enterprise Frontend Redesign Specification
**Version:** AI36 Curated · 2026-05-22  
**Scope:** Full platform frontend — dashboard, browser extensions, Electron app, design system

---

## EXECUTIVE SUMMARY

This document is the single authoritative specification for the complete frontend transformation of the INTEMO AI Email Operations Platform into a world-class, premium enterprise SaaS product. It consolidates all 22 required reports into one structured implementation guide.

**Current state:** Vanilla JS, progressive enhancement, Linear-Light design, functional but not premium.  
**Target state:** Premium enterprise SaaS, 3-theme system, Soft 3D design language, Claude Code–optimized architecture.  
**Tech constraint:** No React/build tool migration — evolve existing vanilla JS architecture with CSS-driven design system.

---

## REPORT 1 — COMPLETE FRONTEND REDESIGN

### Architecture Decision
Maintain vanilla JS + progressive enhancement (no framework migration). The platform is local-first, Electron-served, and the JS layer is already well-structured in `enterprise-ui.js`. Framework migration would break this without meaningful UX gain.

### What Changes
- **Design system**: Full token rebuild with 3-theme architecture
- **CSS**: New `hybrid-theme.css` layer adds depth, 3D system, theme variants
- **HTML**: Sidebar streamlined — clutter removed, nav regrouped
- **Extension popups**: Full premium redesign (SVG logo, better UX hierarchy)
- **Motion**: Lightweight CSS transition system (no GSAP/heavy libs)
- **Icons**: New SVG icon system replacing text-based logos

### Folder Structure (Target)
```
frontend/
  design-system/
    tokens.css          ← 3-theme token system (this spec)
    icons.css           ← SVG icon primitives
  component-library/
    components.js       ← reusable UI helpers

backend/dashboard/
  enterprise-ui.css     ← base design (existing, refined)
  hybrid-theme.css      ← NEW: theme layer, 3D system, hybrid sidebar
  enterprise-ui.js      ← behavior layer (existing)
  index.html            ← simplified sidebar

extensions/shared/
  ui.css                ← premium extension CSS (rebuilt)
  popup.html            ← premium popup structure (rebuilt)
  options.html          ← premium options page
```

---

## REPORT 2 — CLAUDE CODE FRONTEND ARCHITECTURE

### AI-Maintainability Principles
1. **Token-driven** — all colors, spacing, shadow, motion via CSS custom properties
2. **Single responsibility** — each CSS file has one job (tokens / base / theme / extension)
3. **Predictable naming** — `--it-{category}-{variant}` convention throughout
4. **Component classes** — `.btn`, `.btn-primary`, `.card`, `.kpi-card`, `.badge` are stable primitives
5. **Theme via `data-theme`** — switching themes never touches JS or markup, only the root attribute
6. **Zero magic** — no SCSS nesting, no build steps, no preprocessors; every rule is readable as-is

### Claude Code generation targets
- `enterprise-ui.js` views are pure JS with DOM manipulation — easy to extend
- Each "view" function (`initDashboardView`, `initAgentsView`) is isolated
- New views: add a `<section class="view" id="view-X">` in `index.html` + `initXView()` in JS
- New nav items: one `<button class="nav-btn" data-view="X">` in sidebar

---

## REPORT 3 — ENTERPRISE UI MODERNIZATION

### Removed / Simplified
- **Nav mode toggle** ("Show advanced tools" button) — hidden by default; advanced groups collapsed
- **Duplicate nav items** — "Connected Services" and "Connectors" were same view; merged
- **"Smart Workspace" section label** — was confusing; renamed to "Operations"
- **Nav groups with 9 items** — "Operations Support" split into primary nav items + collapsed group
- **Redundant sub-nav entries** — "Email Providers" = same as "Accounts"; removed duplicate

### Added
- **Theme switcher** — Light / Hybrid / Dark toggle in sidebar footer
- **Sidebar footer** — version, theme toggle, account avatar
- **KPI strip** in dashboard — 4 headline metrics above the activity feed
- **Command palette trigger** — `⌘K` chip in sidebar search area

---

## REPORT 4 — UI SIMPLIFICATION

### Before → After
| Before | After |
|--------|-------|
| 6 nav sections + 4 collapsible groups | 3 nav sections, 2 optional collapsed groups |
| 28 nav items visible by default | 12 primary nav items + groups on demand |
| "Show advanced tools" toggle | Advanced items in collapsed `<details>` only |
| Duplicate: Connectors + Connected Services | Single: Connectors |
| Duplicate: Accounts + Email Providers | Single: Accounts |
| "Smart Workspace" label | Removed — confusing name |
| Nav mode switch button | Removed |

### Core Principle
Every nav item must pass: *"Would a user open this at least once per week?"*  
Items failing that test move into collapsed Advanced groups.

---

## REPORT 5 — REMOVED UNNECESSARY ELEMENTS

| Element | Reason Removed |
|---------|---------------|
| `nav-mode-switch` / "Show advanced tools" button | Complex UX anti-pattern |
| Duplicate "Connected Services" in admin nav group | Same as Connectors view |
| Duplicate "Email Providers" in admin nav group | Same as Accounts view |
| "Smart Workspace" section label | Non-descriptive |
| `data-nav-role` basic-client/admin/advanced-admin/business-admin roles with open groups | Replaced by single collapsed Advanced group |
| 5 nested items in "Operations Support" | Moved to collapsed group |
| `nav-mode-toggle` element | Removed entirely |

---

## REPORT 6 — DASHBOARD REDESIGN

### Layout
```
┌─────────────────────────────────────────────────────┐
│  Sidebar (216px)  │  Topbar (52px)                  │
│                   │─────────────────────────────────│
│  Brand            │  KPI Strip (4 metric cards)     │
│  ─────────────    │─────────────────────────────────│
│  Workspace        │                                 │
│  • Dashboard      │  Main content area              │
│  • Inbox          │  (view-specific)                │
│  • AI Processing  │                                 │
│  • Automations    │                                 │
│  • Workflows      │                                 │
│  • Agents         │                                 │
│  • Connectors     │                                 │
│  • Analytics      │                                 │
│  ─────────────    │                                 │
│  System           │                                 │
│  • Admin          │                                 │
│  • Settings       │                                 │
│  ─────────────    │                                 │
│  Advanced ▸       │                                 │
│  ─────────────    │                                 │
│  [Theme] [⌘K]     │                                 │
└───────────────────┴─────────────────────────────────┘
```

### KPI Strip (always visible above main content)
- Emails Processed (today)
- Workflows Executed (active)
- Agents Active
- Pending Approvals

---

## REPORT 7 — NAVIGATION REDESIGN

### Primary Navigation (always visible, 8 items)
1. Dashboard
2. Inbox
3. AI Processing
4. Automations
5. Workflows
6. Agents
7. Connectors
8. Analytics

### Operations Group (collapsed by default)
- Activity Queue, AI Actions, Automation Guides, Service Goals, Team Availability, Service Catalog

### Advanced Group (collapsed, admin-only)
- Risk Overview, Secure Access, Licenses, Budgets, API Access, Webhooks, System Updates, Releases

### System (always visible, 2 items)
- Admin
- Settings

---

## REPORT 8 — LIGHT THEME SYSTEM

### Premium Light Theme (`data-theme="light"`, default)
```css
Background:    #F5F7FB  (soft blue-tinted white)
Surface:       #FFFFFF  (pure white panels)
Surface-2:     #F0F4FA  (subtle panel tint)
Sidebar bg:    #FFFFFF  (same as surface)
Sidebar border:#E8EDFB  (soft blue border)
Text:          #0F172A
Muted:         #64748B
Brand:         #2563EB
Brand accent:  #4F46E5  (indigo for AI features)
```

### Visual character
- Soft white, elevated cards with `box-shadow` depth
- Blue-tinted borders (not gray)
- Subtle gradient buttons with white highlight at top
- No hard black anywhere

---

## REPORT 9 — HYBRID THEME SYSTEM

### Hybrid Enterprise Theme (`data-theme="hybrid"`)
```css
Sidebar bg:    #0F172A  (deep navy — dark sidebar)
Sidebar text:  #CBD5E1
Sidebar active:#FFFFFF
Sidebar hover: rgba(255,255,255,0.06)
Main bg:       #F5F7FB  (light content area — same as light theme)
Surface:       #FFFFFF
```

### Visual character
- Dark sidebar creates depth hierarchy — sidebar feels like a separate "chrome" layer
- Light main content area for content clarity
- Active nav items: white text + brand-left-border indicator
- Sidebar brand area: full dark with logo in white/light

---

## REPORT 10 — 3D BUTTON SYSTEM

### Button Depth Hierarchy
```
Primary:   gradient top→bottom + white inner-top highlight + brand shadow
Secondary: gradient white→off-white + neutral shadow + border
Outline:   transparent bg + colored border + minimal shadow
Ghost:     no border, no bg, hover shows subtle fill
Danger:    red-tinted bg + red border + red shadow
AI:        indigo gradient + indigo shadow (used for AI action buttons)
```

### States
- **Default:** base gradient + layered shadow
- **Hover:** lighter top, stronger shadow, `translateY(-1px)`
- **Active/Press:** inset shadow, `translateY(0)`, darker gradient
- **Focus:** 2px outline at `rgba(brand, 0.40)` offset 2px
- **Disabled:** 40% opacity, no pointer events, no shadow

### Button Size Scale
- `btn-sm`: 6px 11px padding, 12px font
- `btn-md`: 8px 14px (default)
- `btn-lg`: 10px 18px, 14px font
- `btn-xl`: 12px 22px, 15px font (CTAs only)

---

## REPORT 11 — 3D MENU SYSTEM

### Sidebar (3D)
- Left border: 1px with soft blue tint
- Card-style per nav section
- Active item: brand-left-border (3px) + brand-bg-subtle + bold text
- Hover: `translateX(2px)` + background fill
- Icon: 20x20, 1.7px stroke, matches text color; active = brand color

### Dropdown menus
- `box-shadow: 0 8px 32px rgba(15,23,42,0.12), 0 2px 8px rgba(15,23,42,0.08)`
- `border-radius: 12px`
- `backdrop-filter: blur(8px)` on hybrid/dark themes
- Border: `1px solid rgba(148,163,184,0.18)` (subtle)
- Soft entry animation: `translateY(4px) → translateY(0)` + opacity

### Context menus
- Same shadow system as dropdown
- Smaller radius (8px)
- Items: 32px tall, 8px horizontal padding

---

## REPORT 12 — DESIGN SYSTEM

### Token Naming Convention
```
--it-{category}-{variant}-{state}

Categories: bg, surface, text, border, accent, shadow, radius, space, motion
Variants:   base, subtle, muted, strong, inverse
States:     hover, active, focus, disabled
```

### Component Token Usage
| Component | Key Tokens |
|-----------|-----------|
| Button primary | `--it-accent-base`, `--it-shadow-btn-primary` |
| Button secondary | `--it-bg-base`, `--it-border-base`, `--it-shadow-btn` |
| Card | `--it-surface-base`, `--it-shadow-card`, `--it-radius-lg` |
| Sidebar item (active) | `--it-accent-subtle`, `--it-accent-base` (border) |
| Badge success | `--it-green-subtle`, `--it-green-base` |
| Toggle on | `--it-accent-base` gradient |

---

## REPORT 13 — COMPONENT SYSTEM

### Primitive Components
```
.btn                 — base button (default: secondary)
.btn-primary         — primary CTA
.btn-ai              — indigo AI action button
.btn-danger          — destructive action
.btn-ghost           — no background
.btn-sm / .btn-lg    — size modifiers

.card                — surface card with shadow
.card-kpi            — KPI metric card with sparkline area
.card-workflow       — workflow status card
.card-ai             — AI insight card (indigo accent)

.badge               — inline status badge
.badge-success / .badge-warn / .badge-danger / .badge-info

.toggle              — iOS-style toggle switch
.input               — text input with focus ring
.select              — styled select

.kpi-strip           — 4-column KPI row
.kpi-value           — large metric number
.kpi-delta           — up/down delta indicator

.activity-feed       — scrollable activity list
.activity-item       — single feed item
```

---

## REPORT 14 — BRANDING SYSTEM

### Logo Mark
- Primary: Geometric checkmark-in-motion SVG, deep blue gradient `#2563EB → #4F46E5`
- Wordmark: "INTEMO" — Inter ExtraBold, letter-spacing -0.04em
- Tagline: "AI Email Operations" — Inter 500, 11px, muted
- Extension: Same mark at 16/32/48/128px rasterized
- Favicon: Mark only, 32px, no wordmark

### Color Roles
| Role | Color | Usage |
|------|-------|-------|
| Brand | `#2563EB` | CTA buttons, links, active nav |
| AI | `#4F46E5` (Indigo) | AI feature accents, AI buttons |
| Success | `#15803D` | Completed, good, online |
| Warning | `#D97706` | Pending, degraded |
| Danger | `#DC2626` | Error, threat, delete |
| Neutral | `#64748B` | Muted text, icons inactive |

---

## REPORT 15 — APP ICON SYSTEM

### Required Sizes
| Context | Size | Format |
|---------|------|--------|
| Windows taskbar | 16×16 | ICO/PNG |
| Windows app | 32×32 | PNG |
| Windows installer | 256×256 | ICO |
| PWA small | 192×192 | PNG |
| PWA large | 512×512 | PNG |
| macOS dock | 512×512 | ICNS |
| Extension | 16/32/48/128 | PNG |
| Electron tray | 16×16 @2x | PNG |

### Icon Design Language
- Blue-to-indigo gradient background (`#2563EB → #4F46E5`)
- White geometric checkmark with motion trail
- Soft rounded square container (radius 22% of size)
- No text at any size — pure mark
- At 16px: simplified mark, single stroke only

---

## REPORT 16 — FAVICON SYSTEM

### Sizes in `pwa_manifest.json` + HTML
```html
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" href="/icon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
```

### SVG Favicon (scalable, all sizes)
- Single SVG with `viewBox="0 0 32 32"`
- Blue rounded square + white mark
- Works at 16px in browser tab

---

## REPORT 17 — BROWSER EXTENSION REDESIGN

### Current Problems
- Text "IT" as logo — not professional
- 4 stats in a grid with no visual hierarchy
- Generic secondary/settings buttons have no visual weight
- No loading states
- Mobile nav pattern in a 360px-wide popup

### Target State
- **SVG brand mark** — real logo in the brand bar
- **Status card** — prominent service connection indicator
- **Compact KPI row** — 4 stats, cleaner metric cards
- **Quick actions** — primary "Open Dashboard" + secondary pair
- **Threat section** — collapsible, shows only when threats exist
- **Version footer** — subtle, uses muted color

### Popup dimensions
- Width: 360px (unchanged — browser constraint)
- Max height: 580px (browser UI space constraint)
- Content scrollable within wrap

---

## REPORT 18 — ELECTRON APP REDESIGN

### Current State
- `desktop/electron/main.js` — loads `http://127.0.0.1:4597/dashboard`
- CSP is well-configured
- Window: 1280×800 default

### Improvements
- **Window title**: "INTEMO — AI Email Operations" (already set via HTML `<title>`)
- **Traffic light / window chrome**: Native on each OS — no custom titlebar needed
- **Startup**: Show loading screen while API initializes (handled by existing `setup.html` flow)
- **Performance**: `backgroundThrottling: false` (already set), `nodeIntegration: false` (secure)
- **Tray icon**: Use 16×16 brand mark PNG at `/dashboard/assets/icon-tray.png`

### Target `main.js` improvements
- Add `autoHideMenuBar: true` (cleaner on Windows)
- Add `show: false` → show on `ready-to-show` (eliminates white flash)
- Verify CSP includes `style-src 'unsafe-inline'` for CSS custom properties

---

## REPORT 19 — MOTION SYSTEM

### Principles
- All transitions: CSS `transition` only (no JS animation)
- GPU-friendly: only `transform` and `opacity` for animated properties
- Fast feedback: interactive elements ≤ 150ms
- Page transitions: ≤ 220ms fade + subtle translate
- Never animate `width`, `height`, `margin`, `padding` (causes reflow)

### Duration Scale
| Name | Duration | Usage |
|------|----------|-------|
| `--dur-instant` | 80ms | Hover fills, dot indicators |
| `--dur-fast` | 130ms | Button states, toggle |
| `--dur-med` | 200ms | Nav active state, card hover |
| `--dur-slow` | 320ms | Sidebar open/close, modals |
| `--dur-xslow` | 450ms | Page-level fade transitions |

### Easing
- **UI spring**: `cubic-bezier(0.16, 1, 0.3, 1)` — snappy, settles fast
- **Ease out**: `cubic-bezier(0, 0, 0.2, 1)` — exits
- **Linear**: for spinners only

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

---

## REPORT 20 — LOW-RESOURCE OPTIMIZATION

### Memory targets (Windows 11, 4GB RAM)
- Dashboard idle: < 180MB renderer process
- Extension popup: < 25MB
- No CSS `backdrop-filter` in the main dashboard (GPU cost)
- `backdrop-filter` only in extension popup and dropdown menus (small surfaces)

### Rendering strategy
- Use `will-change: transform` only on elements actively animating, remove after animation
- Sidebar shadow: `box-shadow` not `drop-filter`
- Charts: Canvas-based, not SVG (lower DOM node count)
- Virtual scrolling for inbox lists > 200 items (existing behavior, preserve it)

### Asset delivery
- CSS delivered inline-`<link>` before first paint — no JS-injected styles
- No web fonts loaded from external CDNs — Inter from system or local fallback
- Service worker caches CSS/JS aggressively (existing `sw.js`, preserve)

---

## REPORT 21 — AI-FRIENDLY FRONTEND ARCHITECTURE

### Rules for Claude Code generation

**Adding a new view:**
1. Add `PAGES.viewname = ['Title', 'Description']` in `enterprise-ui.js`
2. Add `<button class="nav-btn" data-view="viewname">` in sidebar
3. Add `<section class="view" id="view-viewname">` in `index.html`
4. Add `if (view === 'viewname') initViewnameView();` in `showView()`
5. Write `function initViewnameView() { ... }`

**Adding a new component:**
- All styles go in `hybrid-theme.css` (new components) or `enterprise-ui.css` (base)
- Follow `.component-name` + `.component-name--modifier` BEM-lite convention
- Always use design tokens — no hardcoded colors or sizes

**Adding a new theme:**
- Add `[data-theme="name"] { ... }` block in `tokens.css`
- Override only the tokens that differ from light

**Predictable IDs:**
- View containers: `view-{name}`
- Data displays: `{name}Grid`, `{name}Feed`, `{name}Chart`
- Controls: `{name}RefreshBtn`, `{name}FilterSelect`

---

## REPORT 22 — FINAL UI/UX TRANSFORMATION SUMMARY

### What's being built (this session)
1. ✅ This specification document
2. `frontend/design-system/tokens.css` — 3-theme token system
3. `backend/dashboard/hybrid-theme.css` — 3D design layer + hybrid sidebar
4. `extensions/shared/ui.css` — premium extension popup CSS
5. `extensions/shared/popup.html` — premium extension popup HTML
6. `backend/dashboard/index.html` — simplified sidebar navigation

### Quality bar
The finished frontend must be visually comparable to Linear, Notion, Vercel, or Retool — clean, fast, premium enterprise feel. Every shadow must be purposeful. Every animation must be under 220ms. Every component must be a stable, reusable primitive.

### Not in scope for this session (future work)
- App icon / favicon generation (requires design tools or canvas generation script)
- Electron `main.js` enhancements (low priority, backend security is stable)
- React/Vite migration (not needed — vanilla JS is fast and works)
- Mobile extension UI (out of scope for email desktop platform)
