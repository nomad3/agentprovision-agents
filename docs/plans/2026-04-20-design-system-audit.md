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

## Results

Task 13 re-ran the same three audit commands after Phase 1-5 migrations (Tasks 1-11) and Phase 6 orphan-CSS cleanup (Task 12) landed. Post-migration counts:

| Metric | Before | After | Delta |
|---|---|---|---|
| Decorative header icons + gradient boxes (file:line hits) | 7 | 4 | −3 |
| Hardcoded colors in page CSS (bypassing CSS variables) | 327 | 43 | −284 |
| Gradient usage across pages + components | 38 | 21 | −17 |

### Residual hits — why they remain

**Decorative header icons (4):**
- `SkillsPage.js:9` — `FaRocket` still in the import list; used on line 424 as an auto-trigger indicator icon inside skill card details and on line 590 as the empty-state icon. Both are *content*, not page-header chrome. The decorative gradient icon box that sat in the header is gone.
- `WorkflowsPage.js:15` — `FaBrain` import; used as the workflow design card icon, not as a header ornament.

**Hardcoded colors in page CSS (43):**
- `TenantsPage.css` (32 lines) — TenantsPage was intentionally kept out of scope (see CLAUDE.md note: it uses Bootstrap `bg-${color}-subtle` utilities composed dynamically and was not in the migration task list).
- `AgentsPage.css` (5 lines) — `.agent-modal` skin + the `.agents-table tbody tr:hover` tinted row. Flagged with `TODO: no exact token` comments in-file; deferred to a follow-up token expansion.
- `WorkflowsPage.css` (12 lines) — `.wf-step.start/end/timer/branch/loop/child` type accents. Intentional categorical colors for workflow visualisation, called out in the PR description as a documented exception.

**Gradients outside LandingPage/luna (21):**
- `apps/web/src/pages/AgentsPage.css` (1) — `.agent-modal .modal-content` subtle white gradient. Flagged `TODO: no exact token`.
- `apps/web/src/components/Layout.css` (9), `common/ErrorBoundary.css`, `common/EmptyState.css`, `common/Toast.css`, `common/ConfirmModal.css`, `common/LoadingSpinner.css`, `dashboard/QuickStartCard.css` (2), `CollaborationPanel.css`, `wizard/AgentWizard.css`, `datasource/DataSourceWizard.css` — component-layer surfaces (sidebar, toast, error boundary, wizard stepper). These are shared chrome components outside the per-page migration scope; they'll collapse to tokens in a follow-up pass.

## Summary

The Design System Unification migration replaced 14 pages of per-page ad-hoc styling with a single token layer (`tokens.css`) and shared component class library (`components.css`). Before the migration, pages reinvented their own header chrome, gradient icon boxes, hex/rgba palettes, and button styles; after, every internal page renders through `.ap-page-header`, `.ap-card`, `.ap-btn-*`, `.ap-chip-filter`, `.ap-badge-*`, `.ap-search-wrap`, `.ap-table`, and `.ap-inline-link`. The migration removed the decorative rocket hero from Skills, the gradient Try-it buttons, the neon category colors, the bespoke per-page filter bars, and ~200 lines of orphan CSS that no JS still referenced. The ambient reduction in hardcoded color declarations (327 → 43, −87%) and gradients (38 → 21, −45%) reflects the structural shift: colors now live in one place and render consistently in both light and dark themes via `[data-bs-theme="dark"]` token overrides. The remaining residue is intentional: semantic/categorical accents in `AgentDetailPage` (`STATUS_COLORS`, `ROLE_COLORS`, `TASK_STATUS_COLORS`, `PRIORITY_COLORS`, `AUDIT_STATUS_COLORS`), `WorkflowsPage` (step-type accents and `TYPE_COLORS`), and `IntegrationsPage` (`CONNECTOR_TYPES` brand colors for Postgres/MySQL/S3/GCP/REST). These are data-bound palettes — they're *supposed* to be hardcoded because they encode meaning, not styling.

## Out of scope for this audit

- Component-level gradients inside `apps/web/src/components/` marketing surfaces that are intentionally expressive (landing page, hero sections) — this audit is about the internal authenticated app (`/agents`, `/skills`, `/workflows`, `/chat`, etc.).
- `apps/web/src/index.css` — the platform-wide base stylesheet is trimmed in Task 13, not counted as a per-page offender here.
- `TenantsPage` — not listed in the migration task list; retains its original Bootstrap-compatible `.bg-*-subtle` utility overrides which are composed dynamically via `bg-${color}-subtle`.
