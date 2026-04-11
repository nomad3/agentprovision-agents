# Frontend i18n Refactor Progress

## 2025-10-21

### Summary
- Selected `react-i18next` with `i18next` core and `i18next-browser-languagedetector` to provide async loading, hooks, and built-in locale fallbacks.
- Planned TypeScript-first implementation for all new i18n infrastructure (`apps/web/src/i18n/*`) while keeping existing JS components unchanged until migrated.
- Defined namespace layout and refactor guidelines to extract copy from files such as `apps/web/src/LandingPage.js` and `apps/web/src/components/marketing/data.js`.
- Outlined rollout phases, testing expectations, and documentation updates to ensure reliable language switching.

### Tooling Decisions
- **Core packages**: `i18next`, `react-i18next`, `i18next-browser-languagedetector` (install via workspace package manager).
- **TypeScript support**: add dev dependencies `typescript`, `@types/node`, `@types/react`, `@types/react-dom` if not already present.
- **Typing translations**: introduce `apps/web/src/i18n/locales.d.ts` to declare the translation resource schema for `react-i18next`.
- **Build compatibility**: CRA supports mixed JS/TS; configure `tsconfig.json` under `apps/web/` with `allowJs: true` to avoid blocking legacy files.

### i18n Architecture
- **Initialization**: create `apps/web/src/i18n/i18n.ts` exporting the configured instance. Load resources via `resources/index.ts` to keep imports tree-shakeable.
- **Provider**: wrap `BrowserRouter` inside an `I18nextProvider` from `react-i18next` in `apps/web/src/App.js` (convert to `.tsx` when convenient).
- **Locale persistence**: use language detector order `localStorage -> navigator -> html tag -> fallback`. Store manual overrides with key `agentprovision.lang`.
- **Async loading**: keep initial locales bundled statically; enable code-splitting later if a third language is added.

### Namespace Layout
```
apps/web/src/i18n/
  ├─ i18n.ts
  ├─ locales.d.ts
  └─ locales/
     ├─ en/
     │   ├─ common.json
     │   ├─ landing.json
     │   ├─ auth.json
     │   ├─ datasets.json
     │   └─ chat.json
     └─ es/
         ├─ common.json
         ├─ landing.json
         ├─ auth.json
         ├─ datasets.json
         └─ chat.json
```
- `common`: navigation, footer, buttons, generic labels.
- `landing`: hero, metrics, testimonials, CTA copy from `LandingPage.js` and `marketing/data.js`.
- `auth`: login/register pages.
- `datasets`: `DatasetsPage.js` table headers, modals, alerts.
- `chat`: session list, message composer, empty states.
- Additional namespaces can be added per feature (e.g., `layout`, `settings`).

### Component Refactor Guidelines
- Replace string literals with `t('namespace:key')`; group by section (e.g., `t('landing.hero.title')`).
- Extract arrays like `metrics` or `features` from `marketing/data.js` into translation JSON while keeping icon mappings in code.
- Create memoized helpers when mapping keys to icons (e.g., `const featureIconByKey = { ... }`).
- Avoid embedding HTML in translations; use `Trans` component when line breaks or emphasis are required.
- Maintain existing comments and formatting per repository conventions.

### Language Switch UX
- Add a dropdown in `apps/web/src/components/Layout.js` (header) that calls `i18n.changeLanguage(lang)` and stores the selection.
- Show current language code (EN/ES) and allow expansion for future locales.
- Use `react-bootstrap` `DropdownButton` for minimal changes; keep styling consistent with nav items.

### Rollout Phases & Testing
- **Phase 1**: Install dependencies, add `i18n.ts`, wrap provider, seed `common` + `landing` namespaces. Confirm auto-detect + manual switch.
- **Phase 2**: Localize datasets/chat pages, convert remaining shared components, ensure `DatasetPage` modals correctly re-render on language change.
- **Phase 3**: Document translation key usage, add unit tests for `i18n.ts` initialization, and smoke-test locale toggling.
- **Testing**: add Jest tests to ensure namespaces load, and Cypress/Playwright checks (if available) for language toggle persistence.
- **Documentation**: Update `apps/web/README.md` with instructions for adding new locales.

### Open Items / Next Steps
- Install the new dependencies and generate `tsconfig.json` aligned with CRA defaults.
- Implement `i18n.ts` and wrap `App.js`.
- Migrate `LandingPage` strings into `landing.json` and adjust icon mapping to reference translation keys.
- Repeat extraction for dashboard, datasets, and chat pages per the roadmap phases above.

## 2025-10-22

### Summary
- Installed `i18next`, `react-i18next`, and `i18next-browser-languagedetector` in the CRA app without adding TypeScript tooling per updated guidance.
- Created `apps/web/src/i18n/i18n.js` with locale detection, static resources, and fallback configuration.
- Seeded `common`, `landing`, and `datasets` namespaces with English/Spanish JSON resources.
- Localized `LandingPage.js`, `HeroSection.js`, `Layout.js`, and `DatasetsPage.js`, introducing language switchers for marketing and dashboard contexts.
- Refactored marketing data structures to reference translation keys instead of hardcoded copy.

### Verification
- Manual sanity check switching EN/ES on landing and authenticated layout confirms text updates and persistence via `localStorage`.
- Did not run automated tests; CRA lint complaints about the monorepo `tsconfig.json` remain unrelated to this change.

### Next Steps
- Extend localization to authentication, chat, and remaining dashboard pages using the same namespace pattern.
- Audit API error messages surfaced in UI to ensure translation coverage.
- Add documentation to `apps/web/README.md` for adding locales and running i18n-related tests.
