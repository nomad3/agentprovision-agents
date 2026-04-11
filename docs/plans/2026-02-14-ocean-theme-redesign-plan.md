# AgentProvision Ocean Theme Redesign Plan

**Date:** 2026-02-14
**Status:** Ready for implementation
**Scope:** Full frontend theme switch from dark glassmorphic to light pastel ocean/surf theme

---

## Context

Switching the entire platform from a **dark glassmorphic theme** (teal `#0cd18e` + navy `#2a4d75` on dark `#1a1e24` backgrounds) to a **light pastel ocean/surf/tsunami theme** (white + blue, seafoam accents, coastal mist backgrounds). The redesign keeps the glassmorphism aesthetic but inverts it for light backgrounds.

---

## Color Palette: "Ocean Surf"

### Core Tokens (CSS Custom Properties)

| Token | Old | New | Description |
|---|---|---|---|
| `--surface-page` | `#1a1e24` | `#f0f5fa` | Coastal mist background |
| `--surface-elevated` | `#22272e` | `#ffffff` | White cards/panels |
| `--surface-panel` | `rgba(34,39,46,0.96)` | `rgba(255,255,255,0.92)` | Frosted white glass |
| `--surface-contrast` | `#2d333b` | `#e8eff6` | Input/table backgrounds |
| `--surface-alt` | `#1e2228` | `#f5f8fc` | Alternate sections |
| `--color-foreground` | `#f8fafc` | `#1a2b3c` | Deep navy text |
| `--color-soft` | `rgba(226,232,240,0.9)` | `rgba(45,65,90,0.85)` | Secondary text |
| `--color-muted` | `rgba(148,163,184,0.72)` | `rgba(100,120,145,0.72)` | Tertiary text |
| `--color-primary` | `#0cd18e` | `#2b7de9` | Ocean blue |
| `--color-accent` | `#2a4d75` | `#5ec5b0` | Seafoam teal |
| `--color-highlight` | `#0cd18e` | `#2b7de9` | Same as primary |
| `--color-action` | `#0d6efd` | `#2b7de9` | Unified ocean blue |
| `--color-action-rgb` | `13,110,253` | `43,125,233` | RGB for rgba() |
| `--color-border` | `rgba(148,163,184,0.16)` | `rgba(180,200,220,0.35)` | Subtle blue-grey |
| `--color-border-strong` | `rgba(12,209,142,0.45)` | `rgba(43,125,233,0.45)` | Focus/active border |
| `--color-success` | `#198754` | `#2d9d78` | Sea green |
| `--color-success-rgb` | `25,135,84` | `45,157,120` | |
| `--color-warning` | `#f59e0b` | `#e8a317` | Warm sand |
| `--color-disabled` | `#6c757d` | `#a0b0c0` | Muted coastal grey |
| `--shadow-lg` | `0 35px 70px rgba(26,30,36,0.55)` | `0 35px 70px rgba(100,130,170,0.12)` | Light blue-grey |
| `--shadow-md` | `0 18px 40px rgba(26,30,36,0.5)` | `0 18px 40px rgba(100,130,170,0.08)` | |

### Primary Gradient
- **Old**: `linear-gradient(135deg, #0cd18e, #2a4d75)`
- **New**: `linear-gradient(135deg, #2b7de9, #5ec5b0)` (ocean blue -> seafoam)

### Hardcoded Color Mapping

| Old | New | Notes |
|---|---|---|
| `#f8fafc` (white text) | `#1a2b3c` (navy text) | Everywhere text was light |
| `#a7f3d0` / `#d1fae5` (mint icons) | `#2b7de9` / `#1e5ba6` | Icon/badge colors |
| `#0cd18e` (teal) | `#2b7de9` (ocean blue) | All primary accent uses |
| `#2a4d75` (navy) | `#5ec5b0` (seafoam) | All secondary accent uses |
| `rgba(12,209,142,X)` | `rgba(43,125,233,X)` | Same opacity, new hue |
| `rgba(42,77,117,X)` | `rgba(94,197,176,X)` | Same opacity, new hue |
| `rgba(34,39,46,X)` / `rgba(26,30,36,X)` | `rgba(255,255,255,X)` | Dark bg -> white bg |
| `rgba(0,0,0,0.3-0.6)` | `rgba(100,130,170,0.06-0.15)` | Shadows lighter |
| `rgba(255,255,255,0.05-0.25)` | `rgba(43,125,233,0.03-0.08)` | Overlays |
| `#ef4444` (red) | `#d65a5a` (coral) | Error/danger |
| `#22c55e` / `#10b981` (green) | `#2d9d78` (sea green) | Success |

### Light Glassmorphism Pattern
```css
/* Old dark glass */
background: rgba(34, 39, 46, 0.95);
backdrop-filter: blur(20px);
border: 1px solid rgba(12, 209, 142, 0.22);

/* New light glass */
background: rgba(255, 255, 255, 0.75);
backdrop-filter: blur(20px);
border: 1px solid rgba(180, 200, 220, 0.40);
box-shadow: 0 8px 32px rgba(100, 130, 170, 0.08);
```

---

## Implementation Phases

### Phase 1: Foundation (index.html + index.css)

**Files:**
- `apps/web/public/index.html`
  - Change `data-bs-theme="dark"` to `data-bs-theme="light"`
  - Update `theme-color` meta from `#1a1e24` to `#f0f5fa`
- `apps/web/src/index.css`
  - Rewrite ALL `:root` variables per token table above
  - Rename `[data-bs-theme="dark"]` to `[data-bs-theme="light"]` and update all values
  - Update body background gradients: `rgba(12,209,142,...)` -> `rgba(43,125,233,...)`, `rgba(42,77,117,...)` -> `rgba(94,197,176,...)`
  - `.btn-primary` shadow: `rgba(12,209,142,0.30)` -> `rgba(43,125,233,0.25)`
  - `.nav-dark` bg: `rgba(26,30,36,0.92)` -> `rgba(255,255,255,0.92)`
  - `.hero-section::after` gradients: swap green/navy to ocean blue/seafoam
  - `.badge-glow`: bg `rgba(12,209,142,0.18)` -> `rgba(43,125,233,0.12)`, color `#d1fae5` -> `#1e5ba6`, border `rgba(12,209,142,0.32)` -> `rgba(43,125,233,0.25)`
  - `.hero-spotlight` bg: dark gradients -> white glass
  - `.panel-glass` bg: dark glass -> white glass, border from green to blue
  - `.text-contrast`: `#e2e8f0` -> `#2d4560`
  - `.text-white-75`: light rgba -> dark rgba
  - `.metric-tile` bg: dark -> white glass
  - `.feature-card` bg: dark -> white glass
  - `.gradient-divider`: update color
  - `.footer` bg: dark -> white glass
  - `.icon-pill` / `.icon-pill-sm`: bg green -> blue, color `#a7f3d0` -> `#2b7de9`
  - `.glass-card`: dark glass -> white glass
  - `.section-dark`, `.section-ink`, `.section-contrast`, `.section-highlight`: update all backgrounds/borders
  - `.cta-banner`: green/navy gradient -> blue/seafoam gradient
  - `.logo-badge`: dark bg -> white bg
  - `.list-group-item.active`: green -> blue
  - Remove `filter: invert()` from `.modal-header .btn-close`, `.accordion-button::after`, `.offcanvas-header .btn-close` (7 total occurrences across all CSS files)
  - `.form-control:focus` box-shadow: green -> blue
  - `.dropdown-item.active`: green -> blue
  - Alert text colors: `.alert-danger` `#f8d7da` -> `#8a2c2c`, `.alert-warning` `#fff3cd` -> `#7a5b10`, `.alert-success` `#d1e7dd` -> `#1a5e46`, `.alert-info` `#cff4fc` -> `#2a5f80`
  - `.page-item.active .page-link`: green -> blue
  - `.form-check-input:focus`: green -> blue
  - Update responsive `.nav-dark` breakpoint bg

**Impact:** ~60% of the app since most components use CSS variables.

---

### Phase 2: Layout & Sidebar (Layout.css)

**File:** `apps/web/src/components/Layout.css`

**Changes (17+ hardcoded rgba values):**
- `.layout-container` bg: `#1a1e24` + green/navy radials -> `#f0f5fa` + blue/seafoam radials
- `.sidebar-glass` bg: dark glass -> white glass `rgba(255,255,255,0.92)`, shadow `rgba(0,0,0,0.4)` -> `rgba(100,130,170,0.1)`
- `.sidebar-header` border: `rgba(148,163,184,0.12)` -> `rgba(180,200,220,0.25)`
- `.brand-icon` bg: green/navy -> blue/seafoam, color `#a7f3d0` -> `#2b7de9`, border green -> blue
- `.brand-text` color: `#f8fafc` -> `#1a2b3c`
- `.nav-section-title` color: `rgba(148,163,184,0.7)` -> `rgba(100,120,145,0.72)`, border color update
- `.sidebar-nav-link` color: `rgba(226,232,240,0.8)` -> `rgba(45,65,90,0.85)`
- `.sidebar-nav-link:hover` bg: `rgba(12,209,142,0.1)` -> `rgba(43,125,233,0.08)`, border: green -> blue, color `#f8fafc` -> `#1a2b3c`
- `.sidebar-nav-link.active` bg: green/navy gradient -> blue/seafoam, border green -> blue, color, box-shadow
- `.sidebar-footer` bg: `rgba(26,30,36,0.5)` -> `rgba(255,255,255,0.5)`, border update
- `.user-dropdown-toggle` bg/border: green -> blue, color `#f8fafc` -> `#1a2b3c`
- `.user-email` color: `#f8fafc` -> `#1a2b3c`
- `.user-role` color update
- `.main-content` bg: dark gradient -> light subtle
- Scrollbar track/thumb colors updated

---

### Phase 3: Landing Page & Marketing

**Files:**

#### `apps/web/src/LandingPage.css`
- `.hero-section` bg: `#1a1e24` -> `#f0f5fa`
- `.hero-overlay` radial: dark -> light
- `.floating-card` bg: `rgba(255,255,255,0.1)` -> `rgba(255,255,255,0.75)`, border, shadow, color `white` -> `#1a2b3c`
- `.card-1`, `.card-2`, `.card-3` bg: green/navy gradients -> blue/seafoam
- `.card-icon` color: `#0cd18e` -> `#2b7de9`, filter drop-shadow updated
- `.card-title` color: `rgba(255,255,255,0.9)` -> `#1a2b3c`
- `.card-value` gradient: `#0cd18e, #2a4d75` -> `#2b7de9, #5ec5b0`
- `.card-label` color: `rgba(255,255,255,0.7)` -> `rgba(45,65,90,0.7)`
- `.visual-showcase` bg: dark -> `#f0f5fa`
- `.showcase-item` bg/border/shadow: dark -> light glass
- `.showcase-icon` color: `#0cd18e` -> `#2b7de9`
- `.features-section` bg: `#1a1e24` -> `#f0f5fa`
- `.features-section::before` SVG grid pattern: `rgba(12,209,142,0.1)` -> `rgba(43,125,233,0.1)`
- `.feature-card` bg/border/hover: dark glass -> white glass, green -> blue accents
- `.feature-icon` color: `#0cd18e` -> `#2b7de9`, drop-shadow updated
- `.feature-title` color: `white` -> `#1a2b3c`
- `.feature-description` color: `rgba(255,255,255,0.7)` -> `rgba(45,65,90,0.7)`
- `.cta-section` bg: dark -> light
- `.cta-section::before` SVG dots: `rgba(12,209,142,0.3)` -> `rgba(43,125,233,0.3)`
- `.cta-primary` gradient: green/navy -> blue/seafoam, shadow green -> blue
- `.cta-secondary` border/color: white -> navy
- `.badge-item`, `.stat-item` bg/border: white rgba -> blue tinted
- `.stat-number` gradient: green/navy -> blue/seafoam
- `.stat-label` color: `rgba(255,255,255,0.7)` -> `rgba(45,65,90,0.7)`
- `.logo-badge` bg: dark -> light
- `.gradient-text` gradient: green/mint -> blue/seafoam
- `.panel-glass::before` radial: green -> blue
- Keyframe `glow`: green/navy -> blue/seafoam
- Keyframe `pulse-glow`: navy -> blue
- `.nav-dark .nav-link::before` gradient: green -> blue
- `.cta-banner` gradient: green/navy -> blue/seafoam
- `.cta-banner-content` bg: dark -> white glass
- `.hero-highlight:hover` bg: `rgba(12,209,142,0.08)` -> `rgba(43,125,233,0.06)`
- `.logo-badge::before` gradient: green -> blue
- `.logo-badge:hover` bg/shadow: green -> blue
- `.nav-dark.scrolled` shadow: dark -> light, bg: dark -> white
- `.hover-bg-dark:hover` bg: `rgba(255,255,255,0.05)` -> `rgba(43,125,233,0.04)`
- `.section-with-bg::before` gradient: dark -> light frost
- `.feature-card:hover` box-shadow: green/navy -> blue/seafoam
- `.glass-card:hover, .panel-glass:hover` shadow: green -> blue
- `.showcase-overlay` bg gradient: dark -> light

#### `apps/web/src/components/common/NeuralCanvas.js`
- `config.colors.primary`: `#0cd18e` -> `#2b7de9`
- `config.colors.secondary`: `#2a4d75` -> `#5ec5b0`
- `config.colors.accent`: `#0cd18e` -> `#2b7de9`
- Increase `baseAlpha` from `0.3 + Math.random() * 0.2` to `0.4 + Math.random() * 0.25` for visibility on light bg

#### `apps/web/src/components/marketing/InteractivePreview.js`
- Section bg: `#1e2228`/`#13171c` radial -> `#f0f5fa`/`#e8eff6`
- Dot pattern bg: `#0cd18e` -> `#2b7de9`
- Active button bg: `rgba(12,209,142,0.2)` -> `rgba(43,125,233,0.15)`, color `#0cd18e` -> `#2b7de9`
- Inactive button bg: `rgba(255,255,255,0.05)` -> `rgba(43,125,233,0.04)`, color `rgba(255,255,255,0.5)` -> `rgba(45,65,90,0.5)`
- `text-white` classes -> appropriate light-theme text
- Browser frame bg `rgba(13,17,23,0.95)` -> `rgba(255,255,255,0.95)`
- Box-shadow: dark -> light
- Dot indicator active: `#0cd18e` -> `#2b7de9`, inactive: `rgba(255,255,255,0.2)` -> `rgba(43,125,233,0.15)`

#### `apps/web/src/components/marketing/FeatureDemoSection.js`
- `mockupStyles.badge` green color: `rgba(12,209,142,0.15)` -> `rgba(43,125,233,0.12)`, `#0cd18e` -> `#2b7de9`
- `mockupStyles.connectorLine` gradient: `var(--color-primary), rgba(12,209,142,0.3)` -> `var(--color-primary), rgba(43,125,233,0.3)`
- Agent `color: '#0cd18e'` -> `'#2b7de9'`
- Status dot Running `#0cd18e` -> `#2b7de9`
- Entity colors `#0cd18e` -> `#2b7de9`
- Trend color `#0cd18e` -> `#2b7de9`
- Chat user message bg: `rgba(12,209,142,0.12)` -> `rgba(43,125,233,0.1)`, border `rgba(12,209,142,0.25)` -> `rgba(43,125,233,0.2)`
- `text-white` / `text-light` classes -> `text-dark` / appropriate navy text
- `bg-dark` / `bg-black` classes -> `bg-light` / white equivalents

#### `apps/web/src/components/marketing/HeroSection.js`
- `text-white` class on section -> remove (let CSS handle)
- `variant="outline-light"` -> `variant="outline-dark"` or `variant="outline-secondary"`

---

### Phase 4: Dashboard Page CSS Files

#### `apps/web/src/pages/HomePage.css` (~30 color declarations)
- `.welcome-title` color: `#f8fafc` -> `#1a2b3c`
- `.welcome-subtitle` color: `rgba(226,232,240,0.8)` -> `rgba(45,65,90,0.7)`
- `.section-title` color: `#f8fafc` -> `#1a2b3c`
- `.section-icon` color: `#0cd18e` -> `#2b7de9`
- `.quick-action-card` bg: dark glass -> white glass, border
- `.quick-action-card::before` gradient: green/navy -> blue/seafoam
- `.quick-action-card:hover` border/shadow: green -> blue
- `.action-icon-wrapper` bg: green/navy -> blue/seafoam, border
- `.action-icon` color: `#a7f3d0` -> `#2b7de9`
- `.action-title` color: `#f8fafc` -> `#1a2b3c`
- `.action-description` color: light -> dark text
- `.activity-card` bg: dark glass -> white glass
- `.activity-item` bg: green tinted -> blue tinted, hover states
- `.activity-indicator` gradient: green/navy -> blue/seafoam, box-shadow
- `.activity-label` color: `#f8fafc` -> `#1a2b3c`
- `.tips-card` bg/border: green -> blue
- `.tips-title` color: `#f8fafc` -> `#1a2b3c`
- `.tips-list li::before` color: `#10b981` -> `#2d9d78`
- All `rgba(226,232,240,...)` text -> `rgba(45,65,90,...)`
- All `rgba(148,163,184,...)` borders -> `rgba(180,200,220,...)`

#### `apps/web/src/pages/AgentsPage.css` (~25 color declarations)
- `.page-title` color: `#f8fafc` -> `#1a2b3c`
- `.page-subtitle` color: light -> dark
- `.data-card` bg: dark glass -> white glass, shadow
- `.data-card:hover` border: green -> blue
- `.search-icon-wrapper` bg/border: green -> blue
- `.search-input` border/color: green -> blue, text dark
- `.agents-table` color: `#f8fafc` -> `#1a2b3c`
- `.agents-table thead th` bg: green -> blue, border
- `.agents-table tbody tr:hover` bg: green -> blue
- `.agent-icon` bg: green/navy -> blue/seafoam, color `#a7f3d0` -> `#2b7de9`, border
- `.agent-modal .modal-content` bg: dark glass -> white glass, shadow lighter
- `.agent-modal .modal-header` bg: green -> blue
- `.agent-modal .modal-title` color: `#f8fafc` -> `#1a2b3c`
- `.agent-modal .modal-footer` bg: dark -> light
- Form controls: dark bg -> light bg, green focus -> blue focus
- `.agent-modal .form-range` thumb: `#0cd18e` -> `#2b7de9`
- `.agent-modal .btn-close` REMOVE `filter: brightness(0) invert(1)`

#### `apps/web/src/pages/SettingsPage.css` (~20 color declarations)
- `.page-title` color: `#f8fafc` -> `#1a2b3c`
- `.title-icon` color: `#0cd18e` -> `#2b7de9`
- `.section-icon` color: `#0cd18e` -> `#2b7de9`
- `.section-title` color: `#f8fafc` -> `#1a2b3c`
- `.settings-card` bg: dark glass -> white glass
- `.settings-card:hover` border: green -> blue
- `.form-control` bg: dark -> `#e8eff6`, color `#f8fafc` -> `#1a2b3c`
- `.form-control:focus` bg/border/shadow: green -> blue
- `.settings-switch .form-check-input:checked` bg/border: `#0cd18e` -> `#2b7de9`
- `.security-info strong` color: `#f8fafc` -> `#1a2b3c`
- `.current-plan` bg/border: green -> blue
- `.plan-name` color: `#f8fafc` -> `#1a2b3c`
- `.billing-details` bg: dark -> light
- `.billing-value` color: `#f8fafc` -> `#1a2b3c`
- All `rgba(226,232,240,...)` -> `rgba(45,65,90,...)`
- All `rgba(148,163,184,...)` borders -> `rgba(180,200,220,...)`

#### `apps/web/src/pages/TenantsPage.css` (~20 color declarations)
- `.page-title` color: `#f8fafc` -> `#1a2b3c`
- `.tenant-card` bg: dark glass -> white, shadow lighter
- `.tenant-card:hover` border: green -> blue
- `.icon-pill-sm` bg: green -> blue, color `#6ee7b7` -> `#2b7de9`
- `.stats-table td` color: `#e2e8f0` -> `#2d4560`
- `.info-alert` bg: navy -> seafoam, color `#d1fae5` -> `#1a5e46`
- `.stat-item` bg: `rgba(255,255,255,0.03)` -> `rgba(43,125,233,0.03)`, border
- `.stat-value` color: `#f8fafc` -> `#1a2b3c`
- `.bg-primary-subtle` bg: `rgba(12,209,142,0.15)` -> `rgba(43,125,233,0.12)`
- `.bg-info-subtle` bg: `rgba(42,77,117,0.15)` -> `rgba(94,197,176,0.12)`

#### `apps/web/src/pages/NotebooksPage.css` (~20 color declarations)
- `.reports-table` color: `#f8fafc` -> `#1a2b3c`
- `.reports-table thead th` bg/border: green -> blue
- `.report-row:hover` bg: green -> blue
- `.report-icon` bg: green/navy -> blue/seafoam, color `#a7f3d0` -> `#2b7de9`, border
- `.report-modal .modal-content` bg: dark glass -> white glass, shadow
- `.report-modal .modal-header` bg: green -> blue
- `.report-modal .modal-title` color: `#f8fafc` -> `#1a2b3c`
- `.report-modal .modal-footer` bg: dark -> light
- `.report-modal .btn-close` REMOVE filter
- `.report-modal-icon` colors: same as report-icon
- `.report-data-table` color/bg/borders: green -> blue

#### `apps/web/src/pages/DataPipelinesPage.css` (~10 color declarations)
- `.use-case-card` bg: dark -> white glass
- `.use-case-card:hover` bg/border: green -> blue
- `.use-case-description` color: light -> dark
- `.quick-start` bg: dark -> light
- `.example-item` color: light -> dark
- All `rgba(34,39,46,...)` -> `rgba(255,255,255,...)`

#### `apps/web/src/pages/DataSourcesPage.css`
- `.datasource-card` shadow: `rgba(0,0,0,0.15)` -> `rgba(100,130,170,0.08)`
- `.datasource-card:hover` shadow: `rgba(0,0,0,0.25)` -> `rgba(100,130,170,0.12)`

#### `apps/web/src/pages/IntegrationsPage.css`
- `.stat-total .stat-icon` gradient: `#0cd18e, #8b5cf6` -> `#2b7de9, #8b5cf6`
- `.stat-active .stat-icon` gradient: `#10b981, #34d399` -> `#2d9d78, #5ec5b0`
- `.stat-card:hover` shadow: `rgba(0,0,0,0.25)` -> `rgba(100,130,170,0.12)`
- `.activity-card` shadow: `rgba(0,0,0,0.15)` -> `rgba(100,130,170,0.08)`
- `.syncs-card` shadow: same update

---

### Phase 5: Component CSS Files

#### `apps/web/src/components/common/LoadingSpinner.css`
- `.loading-fullscreen` bg: `rgba(5,11,26,0.95)` -> `rgba(240,245,250,0.95)`
- `.loading-spinner-text` color: `rgba(226,232,240,0.9)` -> `rgba(45,65,90,0.85)`
- `.skeleton-item` gradient: dark blues -> light grey shimmers `rgba(200,215,230,...)`

#### `apps/web/src/components/common/Toast.css`
- `.toast-custom` bg: dark glass -> white glass, shadow lighter
- `.toast-header-custom` bg: green -> blue, color `#f8fafc` -> `#1a2b3c`
- `.toast-header-custom .btn-close` REMOVE filter
- `.toast-body-custom` color: light -> dark
- `.toast-success` border: `#22c55e` -> `#2d9d78`
- `.toast-danger` border: `#ef4444` -> `#d65a5a`
- `.toast-info` border/color: `#2a4d75` -> `#2b7de9`

#### `apps/web/src/components/common/ErrorBoundary.css`
- `.error-boundary-container` bg: dark radials -> light radials, `#1a1e24` -> `#f0f5fa`
- `.error-boundary-card` bg: dark glass -> white glass, shadow lighter
- `.error-boundary-icon` color: `#ef4444` -> `#d65a5a`
- `.error-boundary-title` color: `#f8fafc` -> `#1a2b3c`
- `.error-boundary-description` color: light -> dark
- `.error-boundary-details` bg: dark -> light
- `.error-boundary-summary` color: `#f8fafc` -> `#1a2b3c`, hover bg: green -> blue
- `.error-boundary-stack` color: `#ef4444` -> `#d65a5a`

#### `apps/web/src/components/common/ConfirmModal.css`
- `.confirm-modal .modal-content` bg: dark glass -> white glass, shadow lighter
- `.confirm-modal .btn-close` REMOVE filter
- `.confirm-modal-icon-info` bg/color/border: `#2a4d75` -> `#2b7de9`
- `.confirm-modal-title` color: `#f8fafc` -> `#1a2b3c`
- `.confirm-modal-message` color: light -> dark

#### `apps/web/src/components/common/EmptyState.css`
- `.empty-state-card` bg: dark glass -> white glass, shadow lighter
- `.empty-state-title` color: `#f8fafc` -> `#1a2b3c`
- `.empty-state-description` color: light -> dark
- `.empty-state-info` border/icon: `rgba(42,77,117,...)` -> `rgba(43,125,233,...)`

---

### Phase 6: JS Inline Styles

#### `apps/web/src/pages/BrandingPage.js`
- Default `primary_color` value: `#0cd18e` -> `#2b7de9`
- Default `secondary_color` value: `#2a4d75` -> `#5ec5b0`
- Default `accent_color` value: `#0cd18e` -> `#2b7de9`
- `text-white` classes -> remove or change (inherits from CSS vars)
- `bg-dark text-white` form classes -> remove (inherits from theme)

#### `apps/web/src/components/TaskTimeline.js`
- No hardcoded colors to change (uses CSS vars with fallbacks)
- `bg="dark"` Badge prop -> `bg="secondary"` (for neutral background on light theme)

#### `apps/web/src/components/SkillsConfigPanel.js`
- KEEP all `SKILL_COLORS` unchanged (brand identity: Slack purple, Gmail red, etc.)
- `#10b981` toggle color -> `#2d9d78`
- `boxShadow: rgba(0,0,0,...)` -> `rgba(100,130,170,...)`

#### `apps/web/src/components/OpenClawInstanceCard.js`
- `boxShadow: rgba(0,0,0,0.15)` -> `rgba(100,130,170,0.08)`
- No other hardcoded color changes needed (uses CSS vars)

#### `apps/web/src/components/marketing/FeatureDemoSection.js`
- Already covered in Phase 3 above

#### `apps/web/src/pages/TaskConsolePage.js`
- `bg="dark"` Badge props -> `bg="light"` with appropriate text class
- `variant="outline-light"` Button -> `variant="outline-secondary"`

#### `apps/web/src/pages/MemoryPage.js`
- `text-white` classes -> remove (inherits)
- `bg-dark text-white` form classes -> remove
- `bg-dark bg-opacity-25` import cards -> remove (use default)
- `rgba(255,255,255,0.1)` progress bg -> `rgba(43,125,233,0.08)`

---

## Key Technical Notes

1. **Bootstrap btn-close filter removal** - 7 occurrences across index.css, ConfirmModal.css, Toast.css, NotebooksPage.css, AgentsPage.css. Light theme renders dark X natively.
2. **SVG data URIs** in LandingPage.css grid/dot patterns: change stroke/fill from green to ocean blue.
3. **NeuralCanvas** particles: increase `baseAlpha` for visibility on light bg.
4. **Alert text colors** switch from light (`#f8d7da`) to dark variants (`#8a2c2c`, `#7a5b10`, `#1a5e46`, `#2a5f80`).
5. **Skill-specific brand colors** (Slack purple, Gmail red, etc.) should stay unchanged - they're brand identity.
6. **`text-white` Bootstrap class usage** in JS components needs manual review. On light theme these render white-on-white. Replace with inheriting classes or remove.

---

## Verification Checklist

1. `cd apps/web && npm start` - run dev server
2. Check landing page (`/`) - hero, features, CTA sections
3. Check dashboard (`/dashboard`) - sidebar, cards, tables
4. Check agents page - modals, forms, table rows
5. Check settings - switches, form controls
6. Check chat page - message bubbles, input area
7. Verify no dark blobs or invisible text on any page
8. Verify glassmorphic blur effects still look good on light bg
9. Verify all `filter: invert()` rules removed (7 occurrences)
10. Verify NeuralCanvas particles visible on light background
