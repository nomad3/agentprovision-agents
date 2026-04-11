# Frontend Revamp Context

## Vision

Rebuild the AgentProvision web experience into a cohesive marketing site and operator console that showcases the platform while integrating tightly with the FastAPI backend.

## Guiding Principles

- **Design cohesion**: Establish a reusable design system with consistent typography, spacing, and theming across public and protected areas.
- **Performance & accessibility**: Optimize for fast first paint, responsive layouts, and WCAG-compliant components.
- **API-driven UX**: Leverage the existing FastAPI services for live analytics, tenant management, and auth flows.
- **Developer velocity**: Maintain clear module boundaries, Storybook coverage, and automated testing.

## Architecture Outline

- **Routing**:
  - `app/(public)/marketing/*` – marketing pages.
  - `app/(auth)/*` – sign-in, sign-up, password reset.
  - `app/(protected)/dashboard/*` – operator console guarded by middleware.
- **Layouts**:
  - Public layout with nav/footer and metadata.
  - Protected layout with sidebar, header, and content viewport.
- **Design System**:
  - `components/ui/*` – Tailwind v4 primitives (Button, Card, Badge, Tabs, Table, Dialog, ChartWrapper).
  - `styles/tokens.css` – CSS variables for color, typography, spacing, shadows.
  - Theme switcher leveraging CSS custom properties.
- **Data & State**:
  - `lib/api/client.ts` – fetch helpers with auth headers.
  - `lib/auth/session.ts` – JWT handling via cookies/local storage.
  - TanStack Query for client caching in interactive areas.
- **Content Structure**:
  - Marketing sections composed from JSON/MDX data for hero, features, integrations, compliance, testimonials, pricing, FAQs.
  - Dashboard widgets consuming `/analytics/summary`, `/agents`, `/deployments` endpoints.

## Implementation Roadmap

1. Foundations
   - Install UI dependencies (icons, charting, form helpers).
   - Create design tokens, global styles, and typography scale.
   - Establish route groups and shared layouts.
2. Marketing Site
   - Build primary hero, feature showcases, integration grid, compliance section, testimonials, pricing, CTA, and footer.
   - Ensure responsive behavior, SEO metadata, and structured data.
3. Auth & Session
   - Implement login, registration, reset flows using FastAPI endpoints.
   - Middleware for protected routes; session refresh & sign-out.
4. Operator Console
   - Dashboard shell with navigation, overview metrics, charts, tables.
   - Agents, Deployments, Analytics, Settings pages with forms and table interactions.
5. Testing & QA
   - Storybook for components.
   - Playwright smoke tests for marketing & dashboard flows.
   - Vitest/Jest unit tests for utilities and UI logic.

## Immediate Next Steps

- Verify FastAPI backend health with automated tests.
- Scaffold marketing route structure, layout, and design tokens.
- Implement hero + feature sections with reusable UI primitives.
- Iterate with API integration and dashboard build-out.
