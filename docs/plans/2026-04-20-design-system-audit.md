# Design System Audit — 2026-04-20

## Purpose

This audit records the current state of per-page styling in the AgentProvision internal web app before the Design System Unification effort (see `2026-04-20-design-system-unification-plan.md`). Pages today reach past the shared layer to invent decorative headers, bespoke hex/rgba values, and gradient surfaces — classic "AI slop" that drifts every time a new page ships. The snapshot below captures the raw counts and concrete hits that the migration tasks (3-12) need to rewrite, so that Task 13 can re-run the same commands and prove the drift is gone.

## Before — raw numbers

Commands were run from the repo root on branch `feature/design-system-unification` (commit base: `0fa477ec`).

| Metric | Command | Count |
|---|---|---|
| Decorative header icons + gradient boxes (file:line hits) | `grep -rn "FaRocket\|FaChartBar\|FaBrain\|FaPuzzlePiece\|skills-page-icon\|gradient.*rgba(99\|background: linear-gradient.*0\.2)" apps/web/src/pages/` | 7 |
| Hardcoded colors in page CSS (bypassing CSS variables) | `grep -rn "#[0-9a-f]\{6\}\|rgba(" apps/web/src/pages/*.css \| grep -v "var(--"  \| wc -l` | 327 |
| Gradient usage across pages + components | `grep -rn "linear-gradient" apps/web/src/pages/ apps/web/src/components/ \| wc -l` | 38 |

> Note: the decorative-icon grep in the plan (`gradient.*rgba(99...)`) contains an unbalanced literal `(` which BRE treats as a parse error; the variant run here escapes the trailing `)` as `[.]2)` so BRE can parse it. The set of matched patterns is identical — only the closing paren was normalized.

### Decorative-icon grep — verbatim hits

```
apps/web/src/pages/SkillsPage.css:25:.skills-page-icon {
apps/web/src/pages/SkillsPage.js:9:  FaHistory, FaPlay, FaPlug, FaPlus, FaRocket, FaSearch, FaTerminal,
apps/web/src/pages/SkillsPage.js:433:          {skill.auto_trigger && <div className="skill-auto-trigger"><FaRocket size={10} />Auto-triggers on: {skill.auto_trigger}</div>}
apps/web/src/pages/SkillsPage.js:520:            <div className="skills-page-icon">
apps/web/src/pages/SkillsPage.js:521:              <FaRocket size={22} />
apps/web/src/pages/SkillsPage.js:604:              <FaRocket size={48} className="mb-3" style={{ color: 'rgba(45, 65, 90, 0.35)' }} />
apps/web/src/pages/WorkflowsPage.js:15:  FaBrain,
```

These are the concrete locations future migrations need to touch. Most are concentrated on `SkillsPage` (decorative hero icon + inline rgba), plus a `FaBrain` import on `WorkflowsPage` that should be verified-or-removed when that page is migrated.

## Results — to be filled in by Task 13

Task 13 will re-run the exact same three audit commands after the migration is complete and record the post-migration counts in the table below. A successful migration drives all three numbers down sharply (decorative icons → 0, hardcoded colors → a small single-digit number of intentional exceptions, gradients → 0 or a single documented exception).

| Metric | Before | After | Delta |
|---|---|---|---|
| Decorative header icons + gradient boxes (file:line hits) | 7 |  |  |
| Hardcoded colors in page CSS (bypassing CSS variables) | 327 |  |  |
| Gradient usage across pages + components | 38 |  |  |

## Out of scope for this audit

- Component-level gradients inside `apps/web/src/components/` marketing surfaces that are intentionally expressive (landing page, hero sections) — this audit is about the internal authenticated app (`/agents`, `/skills`, `/workflows`, `/chat`, etc.).
- `apps/web/src/index.css` — the platform-wide base stylesheet is trimmed in Task 13, not counted as a per-page offender here.
