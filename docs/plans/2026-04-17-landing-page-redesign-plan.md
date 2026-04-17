# Landing Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Bootstrap-heavy landing page with a premium Stripe/Loom-quality page using Framer Motion animations, a two-column hero, bento grid features, count-up metrics strip, and infinite integration marquee.

**Architecture:** Decompose the monolithic `LandingPage.js` into focused single-responsibility components under `components/marketing/`. Each section is an independent component receiving no props (reads i18n directly). `LandingPage.js` becomes a thin orchestrator. All animations use Framer Motion — CSS `animate.css` is removed entirely.

**Tech Stack:** React 18, Framer Motion, Bootstrap 5 (layout only), react-i18next, @testing-library/react

**Spec:** `docs/plans/2026-04-17-landing-page-redesign-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `apps/web/src/index.js` | Modify | Remove `animate.css` import |
| `apps/web/package.json` | Modify | Add framer-motion, remove animate.css |
| `apps/web/src/LandingPage.css` | Major rewrite | Remove `.animate-on-scroll`, `.fade-in`, `.slide-up`, `.slide-left`, `.slide-right`, `.stagger` classes; add bento grid, marquee, CSS tokens |
| `apps/web/src/LandingPage.js` | Refactor | Thin orchestrator composing new section components |
| `apps/web/src/components/marketing/LandingNav.js` | New | Sticky nav with scroll blur + Framer Motion stagger |
| `apps/web/src/components/marketing/HeroSection.js` | Full rewrite | Two-column hero, spring entrance, dot grid bg, float animation |
| `apps/web/src/components/marketing/ProductDemo.js` | New (replaces InteractivePreview.js) | Browser mockup + AnimatePresence tab crossfade |
| `apps/web/src/components/marketing/BentoCard.js` | New | Individual bento card (large/small variants), hover lift |
| `apps/web/src/components/marketing/BentoGrid.js` | New | CSS grid container, stagger reveal, 7 cards |
| `apps/web/src/components/marketing/hooks/useCountUp.js` | New (create hooks/ dir) | Count-up animation using Framer Motion `useMotionValue` |
| `apps/web/src/components/marketing/MetricsStrip.js` | New | Dark navy strip, 4 count-up stats |
| `apps/web/src/components/marketing/IntegrationsMarquee.js` | New | Dual-row CSS keyframe logo marquee |
| `apps/web/src/components/marketing/CTASection.js` | Full rewrite | Animated gradient CTA, new i18n keys |
| `apps/web/src/components/marketing/LandingFooter.js` | New | Minimal footer |
| `apps/web/src/i18n/locales/en/landing.json` | Modify | Add nav, statsStrip, integrations, hero.socialProof*; migrate cta; delete ctaBanner |
| `apps/web/src/i18n/locales/es/landing.json` | Modify | Same mutations as en |
| `apps/web/src/components/marketing/FeaturesSection.js` | Delete (Task 15) | Replaced by BentoGrid |
| `apps/web/src/components/marketing/FeatureDemoSection.js` | Delete (Task 15) | Decomposed into BentoGrid + BentoCard |
| `apps/web/src/components/marketing/InteractivePreview.js` | Delete (Task 15) | Replaced by ProductDemo |
| `apps/web/src/components/common/NeuralCanvas.js` | Delete (Task 15) | No longer used after HeroSection rewrite |
| `apps/web/src/components/marketing/data.js` | Delete (Task 15) | Only used by LandingPage.js and FeatureDemoSection.js — orphaned after both are replaced/deleted |
| `apps/web/src/components/common/AnimatedSection.js` | Delete (Task 15) | Only used by LandingPage.js and FeatureDemoSection.js — orphaned after both are replaced/deleted |

---

## Task 1: Foundation — Install framer-motion, remove animate.css, CSS tokens

**Files:**
- Modify: `apps/web/src/index.js`
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/LandingPage.css`

- [ ] **Step 1: Remove the animate.css import from index.js**

  Open `apps/web/src/index.js`. Delete line 4:
  ```js
  import 'animate.css/animate.min.css';
  ```

- [ ] **Step 2: Install framer-motion and uninstall animate.css**

  ```bash
  cd apps/web
  npm install framer-motion
  npm uninstall animate.css
  ```

- [ ] **Step 3: Verify the app still builds**

  ```bash
  cd apps/web
  npm run build 2>&1 | tail -5
  ```
  Expected: `Compiled successfully.`

- [ ] **Step 4: Add CSS design tokens to LandingPage.css**

  Open `apps/web/src/LandingPage.css`. Add at the very top (before any existing rules):

  ```css
  /* Design tokens */
  :root {
    --ap-bg: #ffffff;
    --ap-bg-subtle: #f8fafc;
    --ap-bg-dark: #0a0f1e;
    --ap-text: #0a0a0a;
    --ap-text-muted: #6b7280;
    --ap-blue: #2563eb;
    --ap-teal: #5ec5b0;
    --ap-border: #e2e8f0;
  }
  ```

- [ ] **Step 5: Remove the scroll-animation CSS classes from LandingPage.css**

  The file uses custom CSS scroll animation classes (NOT `animate.css` class names). Delete the blocks for these class names (search for each with your editor):
  - `.animate-on-scroll` and `.animate-on-scroll.is-visible`
  - `.fade-in` and `.fade-in.is-visible`
  - `.slide-up` and `.slide-up.is-visible`
  - `.slide-left` and `.slide-left.is-visible`
  - `.slide-right` and `.slide-right.is-visible`
  - `.stagger` and all `.stagger > *:nth-child(*)` variants
  - `.animate-stagger` and all `.animate-stagger > *:nth-child(*)` variants
  - `@keyframes fadeInStagger` (if present)
  - `.is-visible` (standalone, if any remain)

  Verify they are all gone:
  ```bash
  python3 -c "
  c = open('apps/web/src/LandingPage.css').read()
  for cls in ['animate-on-scroll','fade-in','slide-up','slide-left','slide-right','stagger','animate-stagger','fadeInStagger']:
      print(f'{cls}: {c.count(cls)} occurrences')
  "
  ```
  Expected: all show 0 occurrences.

  These are replaced by Framer Motion. Keep all other CSS in the file.

- [ ] **Step 6: Verify app still builds**

  ```bash
  cd apps/web && npm run build 2>&1 | tail -5
  ```
  Expected: `Compiled successfully.`

- [ ] **Step 7: Commit**

  ```bash
  git add apps/web/src/index.js apps/web/package.json apps/web/package-lock.json apps/web/src/LandingPage.css
  git commit -m "chore: install framer-motion, remove animate.css, add CSS tokens"
  ```

---

## Task 2: i18n — Add translation keys (do this before any component work)

**Files:**
- Modify: `apps/web/src/i18n/locales/en/landing.json`
- Modify: `apps/web/src/i18n/locales/es/landing.json`

All new component tests rely on translated text. Doing this task first ensures tests pass with real string values rather than falling back to key names (e.g. `nav.getStarted` instead of `"Get Started"`).

> **Note:** The existing `hero`, `metrics`, and other keys must NOT be overwritten — these are additive edits.

- [ ] **Step 1: Add new keys to en/landing.json**

  Open `apps/web/src/i18n/locales/en/landing.json` and make these **additive** changes:

  a) Add top-level `nav` key (new):
  ```json
  "nav": {
    "platform": "Platform",
    "features": "Features",
    "integrations": "Integrations",
    "pricing": "Pricing",
    "signIn": "Sign In",
    "getStarted": "Get Started"
  }
  ```

  b) Merge into the existing `hero` object (do NOT replace the whole object — add these two keys alongside the existing ones):
  ```json
  "socialProof": "Trusted by teams at",
  "socialProofFallback": "500+ teams using AgentProvision"
  ```

  c) Add top-level `statsStrip` key (new):
  ```json
  "statsStrip": {
    "tools": { "value": "81", "label": "MCP Tools" },
    "workflows": { "value": "25+", "label": "Native Workflows" },
    "responseTime": { "value": "5.5s", "label": "Avg Response Time" },
    "improvement": { "value": "88%", "label": "Faster Than Baseline" }
  }
  ```

  d) Add top-level `integrations` key (new):
  ```json
  "integrations": {
    "headline": "Connects to everything you already use"
  }
  ```

  e) In the existing `cta` key, rename `"description"` → `"subtext"` and add `"button"`:
  ```json
  "cta": {
    "heading": "Ready to Deploy Your Agent Network?",
    "subtext": "Launch a coordinated network of AI specialists today. Create your account and have Luna, your AI chief of staff, running in minutes.",
    "button": "Get Started Free"
  }
  ```

  f) Delete the `ctaBanner` top-level key entirely (it is no longer read by any component after CTASection is rewritten in Task 10).

- [ ] **Step 2: Validate the JSON**

  ```bash
  python3 -m json.tool apps/web/src/i18n/locales/en/landing.json > /dev/null && echo "valid"
  ```
  Expected: `valid`

- [ ] **Step 3: Apply same mutations to es/landing.json**

  Open `apps/web/src/i18n/locales/es/landing.json` and apply the same structural changes with Spanish translations:

  ```json
  "nav": {
    "platform": "Plataforma",
    "features": "Funciones",
    "integrations": "Integraciones",
    "pricing": "Precios",
    "signIn": "Iniciar Sesión",
    "getStarted": "Comenzar"
  }
  ```
  For `hero.socialProofFallback`: `"Más de 500 equipos usando AgentProvision"`
  For `integrations.headline`: `"Se conecta con todo lo que ya usas"`
  For `statsStrip`: translate labels, keep numeric values identical.
  For `cta`: rename `description` → `subtext`, add `"button": "Comenzar Gratis"`.
  Delete `ctaBanner`.

- [ ] **Step 4: Validate es JSON**

  ```bash
  python3 -m json.tool apps/web/src/i18n/locales/es/landing.json > /dev/null && echo "valid"
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add apps/web/src/i18n/locales/en/landing.json apps/web/src/i18n/locales/es/landing.json
  git commit -m "feat: add landing i18n keys — nav, statsStrip, integrations, hero social proof; migrate cta; delete ctaBanner"
  ```

---

## Task 3: LandingNav — Sticky nav with scroll blur

**Files:**
- Create: `apps/web/src/components/marketing/LandingNav.js`

- [ ] **Step 1: Write the smoke test**

  Create `apps/web/src/components/marketing/__tests__/LandingNav.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import { BrowserRouter } from 'react-router-dom';
  import LandingNav from '../LandingNav';

  const Wrapper = ({ children }) => <BrowserRouter>{children}</BrowserRouter>;

  test('renders nav links', () => {
    render(<LandingNav />, { wrapper: Wrapper });
    expect(screen.getByText(/Get Started/i)).toBeInTheDocument();
    expect(screen.getByText(/Sign In/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test to verify it fails**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern=LandingNav
  ```
  Expected: FAIL — `Cannot find module '../LandingNav'`

- [ ] **Step 3: Create LandingNav.js**

  Create `apps/web/src/components/marketing/LandingNav.js`:

  ```jsx
  import { useEffect, useState } from 'react';
  import { motion } from 'framer-motion';
  import { useNavigate } from 'react-router-dom';
  import { useTranslation } from 'react-i18next';

  const navLinks = ['platform', 'features', 'integrations', 'pricing'];

  export default function LandingNav() {
    const { t } = useTranslation('landing');
    const navigate = useNavigate();
    const [scrolled, setScrolled] = useState(false);

    useEffect(() => {
      const handler = () => setScrolled(window.scrollY > 50);
      window.addEventListener('scroll', handler, { passive: true });
      return () => window.removeEventListener('scroll', handler);
    }, []);

    return (
      <motion.nav
        className={`landing-nav ${scrolled ? 'landing-nav--scrolled' : ''}`}
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="landing-nav__inner">
          <span className="landing-nav__logo">AgentProvision</span>

          <div className="landing-nav__links">
            {navLinks.map((key, i) => (
              <motion.a
                key={key}
                href={`#${key}`}
                className="landing-nav__link"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.06 + 0.2 }}
              >
                {t(`nav.${key}`)}
              </motion.a>
            ))}
          </div>

          <div className="landing-nav__actions">
            <button className="landing-nav__signin" onClick={() => navigate('/login')}>
              {t('nav.signIn')}
            </button>
            <motion.button
              className="landing-nav__cta"
              onClick={() => navigate('/register')}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              transition={{ type: 'spring', stiffness: 400, damping: 17 }}
            >
              {t('nav.getStarted')}
            </motion.button>
          </div>
        </div>
      </motion.nav>
    );
  }
  ```

- [ ] **Step 4: Add nav CSS to LandingPage.css**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* LandingNav */
  .landing-nav {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 1000;
    transition: background 0.3s, box-shadow 0.3s;
  }
  .landing-nav--scrolled {
    background: rgba(255, 255, 255, 0.92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--ap-border);
  }
  .landing-nav__inner {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 24px;
    height: 64px;
    display: flex;
    align-items: center;
    gap: 32px;
  }
  .landing-nav__logo { font-weight: 800; font-size: 18px; color: var(--ap-text); flex-shrink: 0; }
  .landing-nav__links { display: flex; gap: 28px; flex: 1; justify-content: center; }
  .landing-nav__link { font-size: 15px; color: var(--ap-text-muted); text-decoration: none; transition: color 0.2s; }
  .landing-nav__link:hover { color: var(--ap-text); }
  .landing-nav__actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  .landing-nav__signin { background: none; border: none; font-size: 15px; color: var(--ap-text-muted); cursor: pointer; padding: 8px; }
  .landing-nav__signin:hover { color: var(--ap-text); }
  .landing-nav__cta { background: var(--ap-blue); color: #fff; border: none; border-radius: 9999px; padding: 9px 22px; font-size: 15px; font-weight: 600; cursor: pointer; }
  @media (max-width: 767px) {
    .landing-nav__links { display: none; }
    /* Nav shows logo + CTA only on mobile — hamburger menu is out of scope for this plan.
       A hamburger toggle can be added in a follow-up task if needed. */
  }
  ```

- [ ] **Step 5: Run test to verify it passes**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern=LandingNav
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/LandingNav.js apps/web/src/components/marketing/__tests__/LandingNav.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add LandingNav with scroll blur and Framer Motion stagger"
  ```

---

## Task 4: HeroSection — Two-column hero rewrite

**Files:**
- Modify: `apps/web/src/components/marketing/HeroSection.js` (full rewrite)

- [ ] **Step 1: Write the smoke test**

  Create `apps/web/src/components/marketing/__tests__/HeroSection.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import { BrowserRouter } from 'react-router-dom';
  import HeroSection from '../HeroSection';

  test('renders headline and CTAs', () => {
    render(<HeroSection />, { wrapper: ({ children }) => <BrowserRouter>{children}</BrowserRouter> });
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Get Started/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="HeroSection.test"
  ```
  It may pass (existing component) or fail due to NeuralCanvas. Either way, proceed to rewrite.

- [ ] **Step 3: Rewrite HeroSection.js**

  Replace the entire file `apps/web/src/components/marketing/HeroSection.js`:

  ```jsx
  import { useRef } from 'react';
  import { motion, useReducedMotion } from 'framer-motion';
  import { useNavigate } from 'react-router-dom';
  import { useTranslation } from 'react-i18next';

  export default function HeroSection() {
    const { t } = useTranslation('landing');
    const navigate = useNavigate();
    const prefersReducedMotion = useReducedMotion();

    const fadeUp = prefersReducedMotion
      ? { hidden: { opacity: 1, y: 0 }, visible: { opacity: 1, y: 0 } }
      : { hidden: { opacity: 0, y: 24 }, visible: { opacity: 1, y: 0 } };

    const slideRight = prefersReducedMotion
      ? { hidden: { opacity: 1, x: 0 }, visible: { opacity: 1, x: 0 } }
      : { hidden: { opacity: 0, x: 40 }, visible: { opacity: 1, x: 0 } };

    return (
      <section className="hero-v2" id="hero">
        {/* Dot grid background */}
        <div className="hero-v2__dotgrid" aria-hidden="true" />

        <div className="hero-v2__inner">
          {/* Left column */}
          <motion.div
            className="hero-v2__left"
            variants={fadeUp}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <motion.span
              className="hero-v2__badge"
              variants={fadeUp}
              transition={{ delay: 0.1 }}
            >
              {t('hero.badge')}
            </motion.span>

            <motion.h1
              className="hero-v2__headline"
              variants={fadeUp}
              transition={{ delay: 0.2 }}
            >
              {t('hero.title')}
            </motion.h1>

            <motion.p
              className="hero-v2__sub"
              variants={fadeUp}
              transition={{ delay: 0.3 }}
            >
              {t('hero.lead')}
            </motion.p>

            <motion.div
              className="hero-v2__ctas"
              variants={fadeUp}
              transition={{ delay: 0.4 }}
            >
              <motion.button
                className="hero-v2__cta-primary"
                onClick={() => navigate('/register')}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', stiffness: 400, damping: 17 }}
              >
                {t('nav.getStarted')}
              </motion.button>
              <motion.button
                className="hero-v2__cta-ghost"
                onClick={() => navigate('/login')}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', stiffness: 400, damping: 17 }}
              >
                {t('nav.signIn')} →
              </motion.button>
            </motion.div>

            <motion.p
              className="hero-v2__social-proof"
              variants={fadeUp}
              transition={{ delay: 0.5 }}
            >
              {t('hero.socialProofFallback')}
            </motion.p>
          </motion.div>

          {/* Right column — browser chrome mockup */}
          <motion.div
            className="hero-v2__right"
            variants={slideRight}
            initial="hidden"
            animate="visible"
            transition={{ type: 'spring', stiffness: 100, damping: 20, delay: 0.15 }}
          >
            <motion.div
              className="hero-v2__browser"
              animate={prefersReducedMotion ? {} : { y: [0, -8, 0] }}
              transition={{ repeat: Infinity, repeatType: 'reverse', duration: 6, ease: 'easeInOut' }}
            >
              <div className="hero-v2__browser-chrome">
                <span className="chrome-dot chrome-dot--red" />
                <span className="chrome-dot chrome-dot--yellow" />
                <span className="chrome-dot chrome-dot--green" />
                <span className="chrome-address">agentprovision.com/dashboard</span>
              </div>
              <img
                src={`${process.env.PUBLIC_URL}/images/product/dashboard.png`}
                alt="AgentProvision dashboard"
                className="hero-v2__screenshot"
              />
            </motion.div>
          </motion.div>
        </div>
      </section>
    );
  }
  ```

- [ ] **Step 4: Add hero CSS to LandingPage.css**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* HeroSection v2 */
  .hero-v2 {
    position: relative;
    min-height: 100vh;
    background: var(--ap-bg);
    display: flex;
    align-items: center;
    overflow: hidden;
    padding-top: 64px; /* nav height */
  }
  .hero-v2__dotgrid {
    position: absolute;
    inset: 0;
    background-image: radial-gradient(circle, #e2e8f0 1px, transparent 1px);
    background-size: 20px 20px;
    opacity: 0.5;
    pointer-events: none;
  }
  .hero-v2__inner {
    position: relative;
    max-width: 1200px;
    margin: 0 auto;
    padding: 80px 24px;
    display: grid;
    grid-template-columns: 55fr 45fr;
    gap: 60px;
    align-items: center;
    width: 100%;
  }
  .hero-v2__badge {
    display: inline-block;
    font-size: 13px;
    font-weight: 600;
    color: var(--ap-blue);
    background: rgba(37, 99, 235, 0.08);
    border: 1px solid rgba(37, 99, 235, 0.2);
    border-radius: 9999px;
    padding: 4px 14px;
    margin-bottom: 20px;
  }
  .hero-v2__headline {
    font-size: clamp(48px, 5vw, 76px);
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--ap-text);
    line-height: 1.08;
    margin-bottom: 20px;
  }
  .hero-v2__sub {
    font-size: 18px;
    color: var(--ap-text-muted);
    line-height: 1.7;
    margin-bottom: 32px;
    max-width: 480px;
  }
  .hero-v2__ctas { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }
  .hero-v2__cta-primary {
    background: var(--ap-blue); color: #fff; border: none;
    border-radius: 9999px; padding: 14px 28px; font-size: 16px; font-weight: 600; cursor: pointer;
  }
  .hero-v2__cta-ghost {
    background: none; color: var(--ap-text); border: 1.5px solid var(--ap-border);
    border-radius: 9999px; padding: 14px 28px; font-size: 16px; font-weight: 500; cursor: pointer;
  }
  .hero-v2__social-proof { font-size: 13px; color: var(--ap-text-muted); margin: 0; }
  .hero-v2__browser {
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 24px 64px rgba(0,0,0,0.12), 0 4px 16px rgba(0,0,0,0.08);
  }
  .hero-v2__browser-chrome {
    background: #f1f5f9;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid var(--ap-border);
  }
  .chrome-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .chrome-dot--red { background: #ff5f56; }
  .chrome-dot--yellow { background: #ffbd2e; }
  .chrome-dot--green { background: #27c93f; }
  .chrome-address { margin-left: 8px; font-size: 12px; color: var(--ap-text-muted); flex: 1; text-align: center; }
  .hero-v2__screenshot { display: block; width: 100%; height: auto; }
  @media (max-width: 767px) {
    .hero-v2__inner { grid-template-columns: 1fr; padding: 40px 20px; gap: 40px; }
    .hero-v2__right { order: -1; }
    .hero-v2__headline { font-size: 40px; }
  }
  ```

- [ ] **Step 5: Run the hero test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="HeroSection.test"
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/HeroSection.js apps/web/src/components/marketing/__tests__/HeroSection.test.js apps/web/src/LandingPage.css
  git commit -m "feat: rewrite HeroSection — two-col layout, spring animations, NeuralCanvas removed"
  ```

---

## Task 5: ProductDemo — Browser mockup with tab switcher

**Files:**
- Create: `apps/web/src/components/marketing/ProductDemo.js`

Screenshots already exist at `public/images/product/`: `dashboard.png`, `memory.png`, `chat.png`, `agents.png`, `workflows.png`

- [ ] **Step 1: Write the tab interaction test**

  Create `apps/web/src/components/marketing/__tests__/ProductDemo.test.js`:

  ```js
  import { render, screen, fireEvent } from '@testing-library/react';
  import ProductDemo from '../ProductDemo';

  test('renders all 5 tab labels', () => {
    render(<ProductDemo />);
    expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/Agent Memory/i)).toBeInTheDocument();
    expect(screen.getByText(/AI Command/i)).toBeInTheDocument();
    expect(screen.getByText(/Agent Fleet/i)).toBeInTheDocument();
    expect(screen.getByText(/Workflows/i)).toBeInTheDocument();
  });

  test('clicking a tab updates active state', () => {
    render(<ProductDemo />);
    const memoryTab = screen.getByText(/Agent Memory/i);
    fireEvent.click(memoryTab);
    expect(memoryTab.closest('button')).toHaveClass('product-demo__tab--active');
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="ProductDemo.test"
  ```
  Expected: FAIL — module not found

- [ ] **Step 3: Create ProductDemo.js**

  Create `apps/web/src/components/marketing/ProductDemo.js`:

  ```jsx
  import { useState, useRef } from 'react';
  import { motion, AnimatePresence, useInView, useReducedMotion } from 'framer-motion';
  import { useTranslation } from 'react-i18next';

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', img: '/images/product/dashboard.png' },
    { id: 'memory', label: 'Agent Memory', img: '/images/product/memory.png' },
    { id: 'chat', label: 'AI Command', img: '/images/product/chat.png' },
    { id: 'agents', label: 'Agent Fleet', img: '/images/product/agents.png' },
    { id: 'workflows', label: 'Workflows', img: '/images/product/workflows.png' },
  ];

  export default function ProductDemo() {
    const { t } = useTranslation('landing');
    const [active, setActive] = useState('dashboard');
    const ref = useRef(null);
    const isInView = useInView(ref, { once: true, margin: '-100px 0px' });
    const prefersReducedMotion = useReducedMotion();
    const current = tabs.find(t => t.id === active);

    return (
      <section className="product-demo" id="features">
        <div className="product-demo__inner">
          <h2 className="product-demo__heading">See it in action</h2>

          <motion.div
            ref={ref}
            className="product-demo__mockup"
            initial={prefersReducedMotion ? {} : { scale: 0.95, opacity: 0 }}
            animate={isInView ? { scale: 1, opacity: 1 } : {}}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <div className="product-demo__chrome">
              <span className="chrome-dot chrome-dot--red" />
              <span className="chrome-dot chrome-dot--yellow" />
              <span className="chrome-dot chrome-dot--green" />
              <span className="chrome-address">agentprovision.com</span>
            </div>
            <div className="product-demo__screen">
              <AnimatePresence mode="wait">
                <motion.img
                  key={active}
                  src={`${process.env.PUBLIC_URL}${current.img}`}
                  alt={current.label}
                  className="product-demo__screenshot"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                />
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Tab pills */}
          <div className="product-demo__tabs" role="tablist">
            {tabs.map(tab => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={active === tab.id}
                className={`product-demo__tab ${active === tab.id ? 'product-demo__tab--active' : ''}`}
                onClick={() => setActive(tab.id)}
              >
                {tab.label}
                {active === tab.id && (
                  <motion.div
                    layoutId="tab-indicator"
                    className="product-demo__tab-indicator"
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
              </button>
            ))}
          </div>
        </div>
      </section>
    );
  }
  ```

- [ ] **Step 4: Add ProductDemo CSS to LandingPage.css**

  > Note: `.chrome-dot`, `.chrome-dot--red/yellow/green`, and `.chrome-address` CSS classes are defined in Task 4 (HeroSection). ProductDemo shares these class names. If you run Task 5 before Task 4, add those class definitions here too.

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* ProductDemo */
  .product-demo { background: var(--ap-bg-subtle); padding: 100px 24px; }
  .product-demo__inner { max-width: 1100px; margin: 0 auto; }
  .product-demo__heading { text-align: center; font-size: 40px; font-weight: 700; color: var(--ap-text); margin-bottom: 48px; }
  .product-demo__mockup {
    border-radius: 12px; overflow: hidden;
    box-shadow: 0 32px 80px rgba(0,0,0,0.14);
    margin-bottom: 24px;
  }
  .product-demo__chrome {
    background: #f1f5f9; padding: 10px 16px;
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid var(--ap-border);
  }
  .product-demo__screen { position: relative; overflow: hidden; }
  .product-demo__screenshot { display: block; width: 100%; height: auto; }
  .product-demo__tabs {
    display: flex; justify-content: center; gap: 8px; flex-wrap: wrap;
    padding-top: 8px;
  }
  .product-demo__tab {
    position: relative; background: none; border: 1.5px solid var(--ap-border);
    border-radius: 9999px; padding: 8px 20px; font-size: 14px; font-weight: 500;
    color: var(--ap-text-muted); cursor: pointer; transition: color 0.2s, border-color 0.2s;
  }
  .product-demo__tab--active { color: var(--ap-blue); border-color: var(--ap-blue); }
  .product-demo__tab-indicator {
    position: absolute; bottom: -2px; left: 50%; transform: translateX(-50%);
    width: 32px; height: 2px; background: var(--ap-blue); border-radius: 2px;
  }
  ```

- [ ] **Step 5: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="ProductDemo.test"
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/ProductDemo.js apps/web/src/components/marketing/__tests__/ProductDemo.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add ProductDemo with AnimatePresence tab crossfade and layoutId indicator"
  ```

---

## Task 6: BentoCard — Individual card component

**Files:**
- Create: `apps/web/src/components/marketing/BentoCard.js`

- [ ] **Step 1: Write test**

  Create `apps/web/src/components/marketing/__tests__/BentoCard.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import BentoCard from '../BentoCard';
  import { FiZap } from 'react-icons/fi';

  test('renders title and description', () => {
    render(<BentoCard title="AI Command" description="Run agents from chat." icon={FiZap} />);
    expect(screen.getByText('AI Command')).toBeInTheDocument();
    expect(screen.getByText('Run agents from chat.')).toBeInTheDocument();
  });

  test('large variant renders with className bento-card--large', () => {
    const { container } = render(<BentoCard title="X" description="Y" large />);
    expect(container.querySelector('.bento-card--large')).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="BentoCard.test"
  ```

- [ ] **Step 3: Create BentoCard.js**

  Create `apps/web/src/components/marketing/BentoCard.js`:

  ```jsx
  import { motion, useReducedMotion } from 'framer-motion';

  export default function BentoCard({ title, description, icon: Icon, large, className = '', children }) {
    const prefersReducedMotion = useReducedMotion();

    return (
      <motion.div
        className={`bento-card ${large ? 'bento-card--large' : 'bento-card--small'} ${className}`}
        whileHover={prefersReducedMotion ? {} : { y: -4 }}
        transition={{ type: 'spring', stiffness: 400, damping: 17 }}
      >
        {large && <div className="bento-card__accent" />}
        {!large && Icon && (
          <div className="bento-card__icon-wrap">
            <Icon size={32} className="bento-card__icon" />
          </div>
        )}
        <h3 className="bento-card__title">{title}</h3>
        <p className="bento-card__desc">{description}</p>
        {children && <div className="bento-card__content">{children}</div>}
      </motion.div>
    );
  }
  ```

- [ ] **Step 4: Add BentoCard CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* BentoCard */
  .bento-card {
    background: var(--ap-bg);
    border: 1px solid var(--ap-border);
    border-radius: 16px;
    padding: 28px;
    position: relative;
    overflow: hidden;
    cursor: default;
    transition: box-shadow 0.2s;
  }
  .bento-card:hover { box-shadow: 0 12px 40px rgba(0,0,0,0.10); }
  .bento-card--large { padding: 36px; }
  .bento-card--small { background: linear-gradient(135deg, var(--ap-bg-subtle), var(--ap-bg)); }
  .bento-card__accent {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--ap-blue), var(--ap-teal));
  }
  .bento-card__icon-wrap {
    width: 48px; height: 48px; border-radius: 12px;
    background: rgba(37, 99, 235, 0.08);
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 16px;
  }
  .bento-card__icon { color: var(--ap-blue); }
  .bento-card__title { font-size: 18px; font-weight: 600; color: var(--ap-text); margin-bottom: 8px; }
  .bento-card__desc { font-size: 15px; color: var(--ap-text-muted); line-height: 1.6; margin: 0; }
  .bento-card__content { margin-top: 20px; }
  ```

- [ ] **Step 5: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="BentoCard.test"
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/BentoCard.js apps/web/src/components/marketing/__tests__/BentoCard.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add BentoCard component with large/small variants and hover lift"
  ```

---

## Task 7: BentoGrid — Asymmetric feature grid

**Files:**
- Create: `apps/web/src/components/marketing/BentoGrid.js`

Grid uses `grid-template-columns: repeat(6, 1fr)` with explicit span values per card class (see spec for CSS map).

- [ ] **Step 1: Write test**

  Create `apps/web/src/components/marketing/__tests__/BentoGrid.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import BentoGrid from '../BentoGrid';

  test('renders all 7 feature card titles', () => {
    render(<BentoGrid />);
    expect(screen.getByText(/AI Command/i)).toBeInTheDocument();
    expect(screen.getByText(/Agent Memory/i)).toBeInTheDocument();
    expect(screen.getByText(/Multi-Agent/i)).toBeInTheDocument();
    expect(screen.getByText(/Workflows/i)).toBeInTheDocument();
    expect(screen.getByText(/Security/i)).toBeInTheDocument();
    expect(screen.getByText(/Inbox Monitor/i)).toBeInTheDocument();
    expect(screen.getByText(/Code Agent/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="BentoGrid.test"
  ```

- [ ] **Step 3: Create BentoGrid.js**

  Create `apps/web/src/components/marketing/BentoGrid.js`:

  ```jsx
  import { useRef } from 'react';
  import { motion, useInView, useReducedMotion } from 'framer-motion';
  import { FiDatabase, FiUsers, FiGitPullRequest, FiShield, FiMail, FiTerminal } from 'react-icons/fi';
  import BentoCard from './BentoCard';

  const cards = [
    // large: true cards will render children as mini UI mockups — see note below
    { id: 'ai-command', title: 'AI Command', desc: 'Chat-driven agent orchestration. Dispatch multi-step tasks in plain language and watch your agent network execute.', large: true },
    { id: 'memory', title: 'Agent Memory', desc: 'Persistent knowledge graph. Every interaction builds context.', icon: FiDatabase },
    { id: 'multi-agent', title: 'Multi-Agent Teams', desc: '5 specialized teams, zero coordination overhead.', icon: FiUsers },
    { id: 'workflows', title: 'Workflows', desc: 'Visual no-code workflow builder with 25 native templates.', icon: FiGitPullRequest },
    { id: 'security', title: 'Enterprise Security', desc: 'Multi-tenant isolation, encrypted credential vault, JWT auth.', icon: FiShield },
    { id: 'inbox', title: 'Inbox Monitor', desc: 'Proactive email and calendar monitoring, 24/7.', icon: FiMail },
    { id: 'code-agent', title: 'Code Agent', desc: 'Autonomous coding powered by Claude Code CLI. Creates PRs with full audit trails.', large: true },
  ];

  // NOTE: The spec calls for large cards (ai-command, code-agent) to contain mini UI mockups
  // rendered as styled HTML. This plan implements them as plain text cards for the initial
  // delivery. After Task 14 visual verification, if mini mockups are desired, pass styled
  // JSX as `children` to BentoCard for those two entries. This is a deliberate deferral —
  // the BentoCard component already accepts and renders `children` for this purpose.

  const stagger = {
    hidden: {},
    visible: { transition: { staggerChildren: 0.08 } },
  };
  const item = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
  };

  export default function BentoGrid() {
    const ref = useRef(null);
    const isInView = useInView(ref, { once: true, margin: '-80px 0px' });
    const prefersReducedMotion = useReducedMotion();

    return (
      <section className="bento-section" id="platform">
        <div className="bento-section__inner">
          <h2 className="bento-section__heading">Everything your team needs</h2>

          <motion.div
            ref={ref}
            className="bento-grid"
            variants={prefersReducedMotion ? {} : stagger}
            initial="hidden"
            animate={isInView ? 'visible' : 'hidden'}
          >
            {cards.map(card => (
              <motion.div
                key={card.id}
                className={`bento-${card.id}`}
                variants={prefersReducedMotion ? {} : item}
              >
                <BentoCard
                  title={card.title}
                  description={card.desc}
                  icon={card.icon}
                  large={card.large}
                />
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>
    );
  }
  ```

- [ ] **Step 4: Add BentoGrid CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* BentoGrid */
  .bento-section { background: var(--ap-bg); padding: 100px 24px; }
  .bento-section__inner { max-width: 1200px; margin: 0 auto; }
  .bento-section__heading { text-align: center; font-size: 40px; font-weight: 700; color: var(--ap-text); margin-bottom: 48px; }
  .bento-grid {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 16px;
  }
  .bento-ai-command  { grid-column: span 4; }
  .bento-memory      { grid-column: span 2; }
  .bento-multi-agent { grid-column: span 2; }
  .bento-workflows   { grid-column: span 2; }
  .bento-security    { grid-column: span 2; }
  .bento-inbox       { grid-column: span 2; }
  .bento-code-agent  { grid-column: span 4; }
  @media (max-width: 1023px) {
    .bento-grid { grid-template-columns: repeat(2, 1fr); }
    .bento-ai-command, .bento-memory, .bento-multi-agent, .bento-workflows,
    .bento-security, .bento-inbox, .bento-code-agent { grid-column: span 1; }
  }
  @media (max-width: 767px) {
    .bento-grid { grid-template-columns: 1fr; }
    .bento-ai-command, .bento-memory, .bento-multi-agent, .bento-workflows,
    .bento-security, .bento-inbox, .bento-code-agent { grid-column: span 1; }
  }
  ```

- [ ] **Step 5: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="BentoGrid.test"
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/BentoGrid.js apps/web/src/components/marketing/__tests__/BentoGrid.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add BentoGrid with 6-column asymmetric layout and stagger reveal"
  ```

---

## Task 8: useCountUp + MetricsStrip

**Files:**
- Create: `apps/web/src/components/marketing/hooks/useCountUp.js`
- Create: `apps/web/src/components/marketing/MetricsStrip.js`

- [ ] **Step 1: Create the hooks directory and write useCountUp test**

  ```bash
  mkdir -p apps/web/src/components/marketing/hooks
  ```

  Create `apps/web/src/components/marketing/hooks/__tests__/useCountUp.test.js`:

  ```js
  import { renderHook } from '@testing-library/react';
  import { useCountUp } from '../useCountUp';

  test('returns [ref, display] tuple where display is a string', () => {
    const { result } = renderHook(() => useCountUp(81, 1500));
    // Hook returns [ref, displayString]
    expect(Array.isArray(result.current)).toBe(true);
    expect(typeof result.current[1]).toBe('string');
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="useCountUp.test"
  ```

- [ ] **Step 3: Create useCountUp.js**

  Create `apps/web/src/components/marketing/hooks/useCountUp.js`:

  ```js
  import { useEffect, useRef, useState } from 'react';
  import { useInView, useReducedMotion } from 'framer-motion';
  import { animate } from 'framer-motion';

  export function useCountUp(target, duration = 1500) {
    const [display, setDisplay] = useState('0');
    const ref = useRef(null);
    const isInView = useInView(ref, { once: true });
    const prefersReducedMotion = useReducedMotion();

    useEffect(() => {
      if (!isInView) return;
      if (prefersReducedMotion) {
        setDisplay(String(target));
        return;
      }
      const controls = animate(0, target, {
        duration: duration / 1000,
        ease: 'easeOut',
        onUpdate: v => setDisplay(Math.round(v).toString()),
      });
      return () => controls.stop();
    }, [isInView, target, duration, prefersReducedMotion]);

    return [ref, display];
  }
  ```

- [ ] **Step 4: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="useCountUp.test"
  ```
  Expected: PASS

- [ ] **Step 5: Write MetricsStrip test**

  Create `apps/web/src/components/marketing/__tests__/MetricsStrip.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import MetricsStrip from '../MetricsStrip';

  test('renders all 4 stat labels', () => {
    render(<MetricsStrip />);
    expect(screen.getByText(/MCP Tools/i)).toBeInTheDocument();
    expect(screen.getByText(/Native Workflows/i)).toBeInTheDocument();
    expect(screen.getByText(/Avg Response Time/i)).toBeInTheDocument();
    expect(screen.getByText(/Faster Than Baseline/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 6: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="MetricsStrip.test"
  ```

- [ ] **Step 7: Create MetricsStrip.js**

  Create `apps/web/src/components/marketing/MetricsStrip.js`:

  ```jsx
  import { useRef } from 'react';
  import { motion, useInView, useReducedMotion } from 'framer-motion';
  import { useTranslation } from 'react-i18next';
  import { useCountUp } from './hooks/useCountUp';

  const stats = [
    { key: 'tools', target: 81, suffix: '', label: 'MCP Tools' },
    { key: 'workflows', target: 25, suffix: '+', label: 'Native Workflows' },
    { key: 'responseTime', target: 5.5, suffix: 's', label: 'Avg Response Time', decimal: true },
    { key: 'improvement', target: 88, suffix: '%', label: 'Faster Than Baseline' },
  ];

  function StatBlock({ target, suffix, label, decimal }) {
    const [ref, display] = useCountUp(target, 1500);
    const val = decimal ? parseFloat(display).toFixed(1) : display;
    return (
      <div ref={ref} className="metrics-stat">
        <span className="metrics-stat__value">{val}{suffix}</span>
        <span className="metrics-stat__label">{label}</span>
      </div>
    );
  }

  export default function MetricsStrip() {
    const sectionRef = useRef(null);
    const isInView = useInView(sectionRef, { once: true, margin: '-80px 0px' });
    const prefersReducedMotion = useReducedMotion();

    return (
      <motion.section
        ref={sectionRef}
        className="metrics-strip"
        initial={prefersReducedMotion ? {} : { opacity: 0, y: 40 }}
        animate={isInView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.5 }}
      >
        <div className="metrics-strip__inner">
          {stats.map(s => <StatBlock key={s.key} {...s} />)}
        </div>
      </motion.section>
    );
  }
  ```

- [ ] **Step 8: Add MetricsStrip CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* MetricsStrip */
  .metrics-strip {
    background: var(--ap-bg-dark);
    padding: 80px 24px;
  }
  .metrics-strip__inner {
    max-width: 900px; margin: 0 auto;
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 32px; text-align: center;
  }
  .metrics-stat__value { display: block; font-size: 56px; font-weight: 800; color: #fff; line-height: 1; }
  .metrics-stat__label { display: block; font-size: 14px; font-weight: 500; color: var(--ap-teal); margin-top: 8px; }
  @media (max-width: 767px) {
    .metrics-strip__inner { grid-template-columns: repeat(2, 1fr); }
  }
  ```

- [ ] **Step 9: Run MetricsStrip test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="MetricsStrip.test"
  ```
  Expected: PASS

- [ ] **Step 10: Commit**

  ```bash
  git add apps/web/src/components/marketing/hooks/ apps/web/src/components/marketing/MetricsStrip.js apps/web/src/components/marketing/__tests__/MetricsStrip.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add useCountUp hook and MetricsStrip with count-up animations"
  ```

---

## Task 9: IntegrationsMarquee — Dual-row CSS marquee

**Files:**
- Create: `apps/web/src/components/marketing/IntegrationsMarquee.js`
- Create: `apps/web/public/logos/integrations/` (placeholder SVGs)

- [ ] **Step 1: Create logos directory with placeholder SVGs**

  ```bash
  mkdir -p apps/web/public/logos/integrations
  ```

  For each integration name (google, github, meta, whatsapp, jira, gmail, google-calendar, tiktok, slack, huggingface, postgresql, redis), create a minimal SVG placeholder that shows the brand name. Real SVGs can be swapped in later.

  ```bash
  for name in google github meta whatsapp jira gmail google-calendar tiktok slack huggingface postgresql redis; do
    echo "<svg xmlns='http://www.w3.org/2000/svg' width='80' height='32' viewBox='0 0 80 32'><text x='4' y='22' font-family='sans-serif' font-size='13' fill='#94a3b8'>${name}</text></svg>" > apps/web/public/logos/integrations/${name}.svg
  done
  ```

- [ ] **Step 2: Write test**

  Create `apps/web/src/components/marketing/__tests__/IntegrationsMarquee.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import IntegrationsMarquee from '../IntegrationsMarquee';

  test('renders section heading', () => {
    render(<IntegrationsMarquee />);
    expect(screen.getByText(/Connects to everything/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 3: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="IntegrationsMarquee.test"
  ```

- [ ] **Step 4: Create IntegrationsMarquee.js**

  Create `apps/web/src/components/marketing/IntegrationsMarquee.js`:

  ```jsx
  import { useTranslation } from 'react-i18next';

  const logos = [
    { id: 'google', name: 'Google' },
    { id: 'github', name: 'GitHub' },
    { id: 'meta', name: 'Meta Ads' },
    { id: 'whatsapp', name: 'WhatsApp' },
    { id: 'jira', name: 'Jira' },
    { id: 'gmail', name: 'Gmail' },
    { id: 'google-calendar', name: 'Google Calendar' },
    { id: 'tiktok', name: 'TikTok' },
    { id: 'slack', name: 'Slack' },
    { id: 'huggingface', name: 'HuggingFace' },
    { id: 'postgresql', name: 'PostgreSQL' },
    { id: 'redis', name: 'Redis' },
  ];

  function LogoRow({ direction }) {
    // Render logos twice for seamless loop
    const items = [...logos, ...logos];
    return (
      <div className={`marquee-row marquee-row--${direction}`} aria-hidden="true">
        <div className="marquee-track">
          {items.map((logo, i) => (
            <img
              key={`${logo.id}-${i}`}
              src={`${process.env.PUBLIC_URL}/logos/integrations/${logo.id}.svg`}
              alt={logo.name}
              className="marquee-logo"
              loading="lazy"
            />
          ))}
        </div>
      </div>
    );
  }

  export default function IntegrationsMarquee() {
    const { t } = useTranslation('landing');
    return (
      <section className="integrations-showcase" id="integrations">
        <div className="integrations-showcase__inner">
          <h2 className="integrations-showcase__heading">
            {t('integrations.headline')}
          </h2>
        </div>
        <div className="marquee-container">
          <LogoRow direction="left" />
          <LogoRow direction="right" />
          <div className="marquee-fade marquee-fade--left" />
          <div className="marquee-fade marquee-fade--right" />
        </div>
      </section>
    );
  }
  ```

- [ ] **Step 5: Add marquee CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* IntegrationsMarquee */
  .integrations-showcase { background: var(--ap-bg); padding: 100px 0; overflow: hidden; }
  .integrations-showcase__inner { text-align: center; padding: 0 24px; margin-bottom: 48px; }
  .integrations-showcase__heading { font-size: 40px; font-weight: 700; color: var(--ap-text); }
  .marquee-container { position: relative; }
  .marquee-row { overflow: hidden; margin-bottom: 16px; }
  .marquee-track { display: flex; width: max-content; }
  .marquee-row--left .marquee-track { animation: marquee-left 30s linear infinite; }
  .marquee-row--right .marquee-track { animation: marquee-right 30s linear infinite; }
  @keyframes marquee-left { from { transform: translateX(0); } to { transform: translateX(-50%); } }
  @keyframes marquee-right { from { transform: translateX(-50%); } to { transform: translateX(0); } }
  @media (max-width: 767px) {
    .marquee-row--left .marquee-track { animation-duration: 20s; }
    .marquee-row--right .marquee-track { animation-duration: 20s; }
  }
  .marquee-logo { height: 32px; width: auto; margin: 0 32px; filter: grayscale(1) opacity(0.5); transition: filter 0.2s; }
  .marquee-logo:hover { filter: grayscale(0) opacity(1); }
  .marquee-fade {
    position: absolute; top: 0; bottom: 0; width: 120px; pointer-events: none; z-index: 1;
  }
  .marquee-fade--left { left: 0; background: linear-gradient(to right, var(--ap-bg), transparent); }
  .marquee-fade--right { right: 0; background: linear-gradient(to left, var(--ap-bg), transparent); }
  @media (prefers-reduced-motion: reduce) {
    .marquee-track { animation: none !important; }
  }
  ```

- [ ] **Step 6: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="IntegrationsMarquee.test"
  ```
  Expected: PASS

- [ ] **Step 7: Commit**

  ```bash
  git add apps/web/public/logos/ apps/web/src/components/marketing/IntegrationsMarquee.js apps/web/src/components/marketing/__tests__/IntegrationsMarquee.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add IntegrationsMarquee with dual-row CSS keyframe marquee"
  ```

---

## Task 10: CTASection rewrite

**Files:**
- Modify: `apps/web/src/components/marketing/CTASection.js` (full rewrite)

- [ ] **Step 1: Write test**

  Create `apps/web/src/components/marketing/__tests__/CTASection.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import { BrowserRouter } from 'react-router-dom';
  import CTASection from '../CTASection';

  test('renders CTA button', () => {
    render(<CTASection />, { wrapper: ({ children }) => <BrowserRouter>{children}</BrowserRouter> });
    expect(screen.getByText(/Get Started Free/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="CTASection.test"
  ```
  Expected: FAIL — the current CTASection renders `common:cta.startFree` text, not `cta.button`.

- [ ] **Step 3: Rewrite CTASection.js**

  Replace the entire file `apps/web/src/components/marketing/CTASection.js`:

  ```jsx
  import { useRef } from 'react';
  import { motion, useInView, useReducedMotion } from 'framer-motion';
  import { useNavigate } from 'react-router-dom';
  import { useTranslation } from 'react-i18next';

  export default function CTASection() {
    const { t } = useTranslation('landing');
    const navigate = useNavigate();
    const ref = useRef(null);
    const isInView = useInView(ref, { once: true, margin: '-80px 0px' });
    const prefersReducedMotion = useReducedMotion();

    return (
      <section className="cta-v2">
        <motion.div
          ref={ref}
          className="cta-v2__inner"
          initial={prefersReducedMotion ? {} : { opacity: 0, scale: 0.98 }}
          animate={isInView ? { opacity: 1, scale: 1 } : {}}
          transition={{ duration: 0.5 }}
        >
          <h2 className="cta-v2__heading">{t('cta.heading')}</h2>
          <p className="cta-v2__sub">{t('cta.subtext')}</p>
          <motion.button
            className="cta-v2__btn"
            onClick={() => navigate('/register')}
            whileHover={prefersReducedMotion ? {} : { scale: 1.02 }}
            whileTap={prefersReducedMotion ? {} : { scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 400, damping: 17 }}
          >
            {t('cta.button')}
          </motion.button>
        </motion.div>
      </section>
    );
  }
  ```

- [ ] **Step 3: Add CTASection CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* CTASection v2 */
  .cta-v2 {
    background: linear-gradient(135deg, var(--ap-blue), var(--ap-teal));
    background-size: 200% 200%;
    animation: gradientShift 8s ease infinite;
    padding: 100px 24px;
    text-align: center;
  }
  @keyframes gradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
  }
  .cta-v2__inner { max-width: 640px; margin: 0 auto; }
  .cta-v2__heading { font-size: 44px; font-weight: 800; color: #fff; margin-bottom: 16px; }
  .cta-v2__sub { font-size: 18px; color: rgba(255,255,255,0.85); margin-bottom: 36px; }
  .cta-v2__btn {
    background: #fff; color: var(--ap-blue); border: none;
    border-radius: 9999px; padding: 16px 40px;
    font-size: 17px; font-weight: 700; cursor: pointer;
    box-shadow: 0 4px 24px rgba(0,0,0,0.15);
  }
  @media (prefers-reduced-motion: reduce) {
    .cta-v2 { animation: none; }
  }
  ```

- [ ] **Step 4: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="CTASection.test"
  ```
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add apps/web/src/components/marketing/CTASection.js apps/web/src/components/marketing/__tests__/CTASection.test.js apps/web/src/LandingPage.css
  git commit -m "feat: rewrite CTASection with animated gradient and Framer Motion entrance"
  ```

  > Note on step numbering: the original Step 2 is now Step 3, Step 3 is Step 4, etc. The run-fail step was inserted above as Step 2.

---

## Task 11: LandingFooter

**Files:**
- Create: `apps/web/src/components/marketing/LandingFooter.js`

- [ ] **Step 1: Write test**

  Create `apps/web/src/components/marketing/__tests__/LandingFooter.test.js`:

  ```js
  import { render, screen } from '@testing-library/react';
  import { BrowserRouter } from 'react-router-dom';
  import LandingFooter from '../LandingFooter';

  test('renders footer with nav links', () => {
    render(<LandingFooter />, { wrapper: ({ children }) => <BrowserRouter>{children}</BrowserRouter> });
    expect(screen.getByText(/AgentProvision/i)).toBeInTheDocument();
    expect(screen.getByText(/Platform/i)).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run test — expect FAIL**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="LandingFooter.test"
  ```

- [ ] **Step 3: Create LandingFooter.js**

  Create `apps/web/src/components/marketing/LandingFooter.js`:

  ```jsx
  import { useTranslation } from 'react-i18next';
  import { FiGithub, FiTwitter, FiLinkedin } from 'react-icons/fi';

  export default function LandingFooter() {
    const { t } = useTranslation('landing');

    return (
      <footer className="landing-footer">
        <div className="landing-footer__inner">
          <div className="landing-footer__brand">
            <span className="landing-footer__logo">AgentProvision</span>
            <p className="landing-footer__tagline">Enterprise AI orchestration, built for teams that ship.</p>
          </div>

          <nav className="landing-footer__nav">
            <a href="#platform" className="landing-footer__link">Platform</a>
            <a href="#features" className="landing-footer__link">Features</a>
            {/* TODO: replace with real docs URL when available */}
            <a href="#" className="landing-footer__link">Docs</a>
            {/* TODO: replace with real GitHub org URL when available */}
            <a href="#" className="landing-footer__link">GitHub</a>
          </nav>

          <div className="landing-footer__social">
            <a href="#" className="landing-footer__social-link" aria-label="GitHub"><FiGithub size={20} /></a>
            <a href="#" className="landing-footer__social-link" aria-label="Twitter"><FiTwitter size={20} /></a>
            <a href="#" className="landing-footer__social-link" aria-label="LinkedIn"><FiLinkedin size={20} /></a>
          </div>
        </div>
        <p className="landing-footer__copy">© {new Date().getFullYear()} AgentProvision. All rights reserved.</p>
      </footer>
    );
  }
  ```

- [ ] **Step 4: Add footer CSS**

  Append to `apps/web/src/LandingPage.css`:

  ```css
  /* LandingFooter */
  .landing-footer { background: var(--ap-bg-subtle); border-top: 1px solid var(--ap-border); padding: 48px 24px 24px; }
  .landing-footer__inner {
    max-width: 1200px; margin: 0 auto;
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 32px; flex-wrap: wrap;
    margin-bottom: 32px;
  }
  .landing-footer__logo { font-weight: 800; font-size: 17px; color: var(--ap-text); }
  .landing-footer__tagline { font-size: 14px; color: var(--ap-text-muted); margin-top: 6px; max-width: 260px; }
  .landing-footer__nav { display: flex; gap: 24px; flex-wrap: wrap; }
  .landing-footer__link { font-size: 14px; color: var(--ap-text-muted); text-decoration: none; }
  .landing-footer__link:hover { color: var(--ap-text); }
  .landing-footer__social { display: flex; gap: 16px; }
  .landing-footer__social-link { color: var(--ap-text-muted); }
  .landing-footer__social-link:hover { color: var(--ap-text); }
  .landing-footer__copy { text-align: center; font-size: 13px; color: var(--ap-text-muted); margin: 0; }
  ```

- [ ] **Step 5: Run test**

  ```bash
  cd apps/web && npm test -- --watchAll=false --testPathPattern="LandingFooter.test"
  ```
  Expected: PASS

- [ ] **Step 6: Commit**

  ```bash
  git add apps/web/src/components/marketing/LandingFooter.js apps/web/src/components/marketing/__tests__/LandingFooter.test.js apps/web/src/LandingPage.css
  git commit -m "feat: add LandingFooter"
  ```

---

## Task 12: Wire LandingPage.js

**Files:**
- Modify: `apps/web/src/LandingPage.js` (major refactor)

Replace the entire LandingPage.js with a thin orchestrator. The current file is 291 lines with hardcoded sections, Bootstrap components, and inline logic. Replace it.

- [ ] **Step 1: Audit current imports in LandingPage.js**

  Check which existing components it imports:
  ```bash
  grep "^import" apps/web/src/LandingPage.js
  ```

- [ ] **Step 2: Rewrite LandingPage.js**

  Replace the entire file `apps/web/src/LandingPage.js`:

  ```jsx
  import React from 'react';
  import LandingNav from './components/marketing/LandingNav';
  import HeroSection from './components/marketing/HeroSection';
  import ProductDemo from './components/marketing/ProductDemo';
  import BentoGrid from './components/marketing/BentoGrid';
  import MetricsStrip from './components/marketing/MetricsStrip';
  import IntegrationsMarquee from './components/marketing/IntegrationsMarquee';
  import CTASection from './components/marketing/CTASection';
  import LandingFooter from './components/marketing/LandingFooter';
  import './LandingPage.css';

  export default function LandingPage() {
    return (
      <>
        <LandingNav />
        <main>
          <HeroSection />
          <ProductDemo />
          <BentoGrid />
          <MetricsStrip />
          <IntegrationsMarquee />
          <CTASection />
        </main>
        <LandingFooter />
      </>
    );
  }
  ```

- [ ] **Step 3: Verify the app builds**

  ```bash
  cd apps/web && npm run build 2>&1 | tail -10
  ```
  Expected: `Compiled successfully.`

  If there are import errors from the old components (FeaturesSection, FeatureDemoSection, etc.), they are now unused imports — ignore until Task 13.

- [ ] **Step 4: Run all tests**

  ```bash
  cd apps/web && npm test -- --watchAll=false --ci 2>&1 | tail -15
  ```
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git add apps/web/src/LandingPage.js
  git commit -m "feat: refactor LandingPage.js to thin orchestrator with new section components"
  ```

---

## Task 13: Visual verification in browser

- [ ] **Step 1: Start the dev server**

  ```bash
  cd apps/web && npm start
  ```

- [ ] **Step 2: Open http://localhost:3000 and verify each section**

  Check in order:
  - [ ] Nav is fixed, transparent on load, blurs on scroll
  - [ ] Hero is full viewport height, two columns, product image floats
  - [ ] ProductDemo tabs switch with crossfade, indicator slides
  - [ ] Bento grid is asymmetric (4+2 / 2+2+2 / 2+4), cards lift on hover
  - [ ] Metrics strip is dark navy, numbers count up on scroll
  - [ ] Marquee rows scroll in opposite directions, fade at edges
  - [ ] CTA gradient animates, button springs on hover
  - [ ] Footer shows three columns

- [ ] **Step 3: Check mobile at 375px**

  Use browser DevTools to set viewport to 375px. Verify:
  - [ ] Nav hides link row, shows logo + CTA only
  - [ ] Hero stacks to single column
  - [ ] Bento grid is 1 column
  - [ ] Metrics wraps to 2×2

- [ ] **Step 4: Fix any visual issues found before proceeding**

---

## Task 14: Cleanup — Delete deprecated components

Only run this task after Task 13 visual verification passes.

- [ ] **Step 1: Verify NeuralCanvas is unused**

  ```bash
  grep -r "NeuralCanvas" apps/web/src/ --include="*.js"
  ```
  Expected: no results (HeroSection was rewritten in Task 3)

- [ ] **Step 2: Delete deprecated files**

  ```bash
  rm apps/web/src/components/marketing/FeaturesSection.js
  rm apps/web/src/components/marketing/FeatureDemoSection.js
  rm apps/web/src/components/marketing/InteractivePreview.js
  rm apps/web/src/components/marketing/data.js
  rm apps/web/src/components/common/NeuralCanvas.js
  rm apps/web/src/components/common/AnimatedSection.js
  ```

  `data.js` and `AnimatedSection.js` are only imported by `LandingPage.js` (now rewritten to not use them) and `FeatureDemoSection.js` (deleted above). They are orphaned after this task.

- [ ] **Step 3: Verify build still passes**

  ```bash
  cd apps/web && npm run build 2>&1 | tail -5
  ```
  Expected: `Compiled successfully.`

- [ ] **Step 4: Run full test suite**

  ```bash
  cd apps/web && npm test -- --watchAll=false --ci 2>&1 | tail -15
  ```
  Expected: PASS

- [ ] **Step 5: Commit**

  ```bash
  git rm apps/web/src/components/marketing/FeaturesSection.js \
         apps/web/src/components/marketing/FeatureDemoSection.js \
         apps/web/src/components/marketing/InteractivePreview.js \
         apps/web/src/components/marketing/data.js \
         apps/web/src/components/common/NeuralCanvas.js \
         apps/web/src/components/common/AnimatedSection.js
  git commit -m "chore: delete deprecated marketing components (FeaturesSection, FeatureDemoSection, InteractivePreview, NeuralCanvas, data.js, AnimatedSection)"
  ```

---

## Task 15: Final build and PR

- [ ] **Step 1: Run full test suite one last time**

  ```bash
  cd apps/web && npm test -- --watchAll=false --ci
  ```

- [ ] **Step 2: Production build**

  ```bash
  cd apps/web && npm run build 2>&1 | tail -5
  ```

- [ ] **Step 3: Create PR**

  ```bash
  git push origin HEAD
  gh pr create --title "feat: premium landing page redesign with Framer Motion" \
    --body "$(cat <<'EOF'
  ## Summary
  - Full landing page redesign: LandingNav, HeroSection (2-col + spring animations), ProductDemo (AnimatePresence tabs), BentoGrid (7-card asymmetric), MetricsStrip (count-up), IntegrationsMarquee (CSS marquee), CTASection (animated gradient), LandingFooter
  - Framer Motion replaces animate.css entirely
  - prefers-reduced-motion respected in all animated components
  - Mobile responsive: 1-col hero, 1-col bento, 2×2 metrics on < 768px
  - i18n: added nav, statsStrip, integrations keys; migrated cta; deleted unused ctaBanner

  ## Test plan
  - [ ] All component smoke tests pass (CI)
  - [ ] ProductDemo tab interaction test passes
  - [ ] Production build compiles without warnings
  - [ ] Visual verification at 1440px desktop and 375px mobile
  - [ ] Scroll animations trigger correctly on each section
  EOF
  )" --assignee nomade
  ```
