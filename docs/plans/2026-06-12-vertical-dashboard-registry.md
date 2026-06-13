# Vertical Workspace Registry Plan

Date: 2026-06-12
Status: reviewed by Luna and Claudia

## Problem

The veterinary MVP dashboard should not become a permanent hardcoded
AgentProvision surface. `/practice` is useful for the current tenant, but
AgentProvision is a generic orchestration platform. Other tenants may need a
sales CRM workspace, legal matters workspace, healthcare ops workspace, field
service workspace, or fully custom ERP-style board without seeing veterinary
agents, PMS readiness, SOAP flows, or vet-specific workflows.

The platform needs a way to install vertical-specific workspaces per tenant
while keeping the core dashboard generic.

## Product Direction

AgentProvision should have a generic orchestration shell plus tenant-enabled
workspace packs.

Core AgentProvision owns the primitives:

- agents
- workflows
- files and knowledge
- approvals
- tasks, cases, queues
- integrations
- metrics
- audit and status

Workspace packs compose those primitives for a specific operating model:

- veterinary practice: patients, intake, SOAP drafts, billing review,
  inventory, PMS prep, cardiology referrals
- sales CRM: accounts, deals, follow-ups, proposals, revenue risk
- legal ops: matters, documents, deadlines, review gates
- healthcare ops: referrals, charts, billing exceptions, compliance queues
- custom ERP: tenant-defined boards and widgets

PMS should remain a veterinary vertical integration category, not a global
AgentProvision concept. The global concept is "external system readiness" or
"system-of-record integration"; PMS is one implementation in the vet pack.

## Current PR Decision

Do not merge the hardcoded vet dashboard PR as final product direction.

Use it as a prototype input for:

- vet widget content
- sample Dr. Angelo / Dr. Brett operating data
- file-first language
- approval and review gates
- widget tests

Then refactor the work into the workspace registry architecture below.

## Target Model

### Workspace Pack

A workspace pack is a composition layer over existing AgentProvision
primitives. It declares views, widgets, setup checks, labels, and bindings to
agents/workflows/integrations. It should not own a separate business-object
model unless that object already belongs in the platform domain.

Phase 1 required fields:

- `slug`: stable route key, for example `vet-practice`
- `label`: sidebar/display name
- `description`
- `status`: `draft`, `staging`, `production`, `deprecated`
- `icon`
- `version`
- `feature_flag`
- `required_capabilities`
- `widgets`
- `setup_requirements`

Derived fields:

- canonical route: `/workspaces/{slug}`
- optional vertical/category for catalog filtering only

Example:

```json
{
  "slug": "vet-practice",
  "label": "Vet Practice",
  "route": "/workspaces/vet-practice",
  "required_capabilities": ["drive_packets", "approval_gates", "agent_handoffs"],
  "widgets": [
    "launch_brief",
    "daily_work_queue",
    "file_packet_flows",
    "review_gates",
    "agent_fleet",
    "system_readiness",
    "specialist_referral_lane"
  ]
}
```

### Manifest Format

Use typed Python registry definitions for the MVP, mirroring native workflow
templates. Do not introduce file-authored or non-engineer-authored manifests
until the pack contract has survived at least two native packs.

### Tenant Workspace Install

Tenants should only see workspaces they have installed or that are globally
core.

Suggested persisted shape:

- `tenant_workspace_installs`
  - `id`
  - `tenant_id`
  - `workspace_slug`
  - `status`
  - `display_order`
  - `pinned`
  - `config` JSON
  - `installed_by`
  - `created_at`
  - `updated_at`
  - `installed_version`
  - `enabled_at`
  - `disabled_at`

The tenant install state should be persisted so sidebar visibility, ordering,
and enablement are tenant-scoped.

Pack lifecycle must be explicit:

- install
- enable
- disable
- upgrade
- rollback
- config migration
- audit

Every lifecycle transition should write an audit event. Disabled packs must not
appear in navigation or allow direct route/widget access.

### Binding Model

Widget bindings should use stable slugs/keys, not UUIDs:

- agent capability keys, not specific agent ids, whenever possible
- workflow template names/source keys, not tenant copy ids
- integration names, not integration config ids
- saved search / queue keys, not ad hoc filters embedded in React

The provider resolves those bindings for the current tenant at request time.

### Widget Provider

Each workspace pack exposes widgets through a provider interface.

Provider responsibilities:

- return workspace metadata
- return widget payloads
- enforce tenant isolation
- expose setup/empty states
- avoid claiming unconnected integrations are live
- enforce user RBAC in addition to tenant scoping
- return typed widget states

Example service interface:

```python
class WorkspaceProvider(Protocol):
    slug: str

    def descriptor(self, db: Session, tenant_id: UUID) -> dict: ...

    def widget(
        self,
        db: Session,
        tenant_id: UUID,
        widget_key: str,
        user_id: UUID | None = None,
    ) -> dict: ...
```

The vet provider should wrap the existing `build_vet_practice_dashboard`
read model and split it into widgets.

Every widget response must use a formal payload envelope:

```json
{
  "key": "daily_work_queue",
  "state": "ready | setup_required | empty | error | missing_permission | unsupported",
  "data": {},
  "setup_blockers": [],
  "updated_at": "2026-06-12T00:00:00Z",
  "example": false
}
```

State meanings:

- `ready`: live tenant-backed data is available
- `setup_required`: dependencies are missing
- `empty`: configured but no records yet
- `error`: provider failed safely
- `missing_permission`: current user cannot view this widget
- `unsupported`: pack exists but feature flag/provider is unavailable

Widgets must not render synthetic metrics as if they are live. Example data is
allowed only when clearly marked as `example: true` and visually labeled as an
example or setup preview.

Widget payloads should also define refresh behavior:

- `cache_ttl_seconds`
- `refreshable`
- `last_success_at`
- `error_code` when `state == "error"`

## Layout Model

For the MVP:

- pack default layout is defined in the typed registry
- tenant-level layout override is allowed only for display order and pinning
- no per-user layout personalization
- no drag/drop builder

This avoids building a workspace-builder product before the pack model is proven.

## API Plan

Add tenant-scoped workspace routes:

- `GET /api/v1/workspaces`
  - returns lightweight workspace descriptors enabled for the current tenant
  - includes core workspace plus installed vertical/custom packs
  - never returns heavy widget payloads
- `GET /api/v1/workspaces/catalog`
  - returns available packs the tenant can install, subject to role
- `GET /api/v1/workspaces/{slug}`
  - returns descriptor, layout, setup state, and initial widget payloads
- `GET /api/v1/workspaces/{slug}/widgets/{widget_key}`
  - returns one widget payload
- `POST /api/v1/workspaces/{slug}/install`
  - admin-only install
- `PATCH /api/v1/workspaces/{slug}/install`
  - admin-only order/config/status update
- `DELETE /api/v1/workspaces/{slug}/install`
  - admin-only disable, soft-delete preferred

Internal/provisioning route:

- `POST /api/v1/provision/workspace-pack/internal`
  - installs a workspace pack for a tenant during vertical provisioning

All routes must filter by `tenant_id`.

Route gating:

- uninstalled pack: `404`
- installed but incomplete pack: `200` with `setup_required`
- installed but current user lacks access: `403` or widget-level
  `missing_permission`, depending on whether the whole workspace or only one
  widget is restricted

Route responses must never be cached globally unless the cache key includes
tenant, user/role, workspace slug, widget key, and pack version. Dynamic sidebar
responses are especially sensitive because they reveal installed capabilities.

## Permissions

Separate three permission layers:

- install/manage workspace pack
- view workspace shell
- access underlying widget data, agents, files, workflows, or integrations

Admin install rights do not automatically grant access to every underlying
agent/data source. Widget providers must enforce the deepest relevant access
check server-side.

## Catalog Scope

MVP catalog scope:

- global native pack registry
- tenant-plan/feature-flag gated
- role gated for install/manage actions
- vertical provisioning can auto-install a pack without making every catalog
  pack visible to all tenants

## Frontend Plan

### Dynamic Sidebar

Replace the hardcoded `Vet Practice` sidebar item with workspace entries from
`GET /workspaces`.

Behavior:

- core AgentProvision pages remain static
- enabled workspace packs appear under a `Workspaces` sidebar group
- tenants without `vet-practice` never see veterinary navigation
- `/practice` remains a compatibility alias that redirects to
  `/workspaces/vet-practice` only if installed

The dynamic sidebar should load lightweight descriptors only. It should not
block on heavy widget payloads.

### Workspace Router

Add:

- `/workspaces`
  - list installed workspaces
- `/workspaces/:slug`
  - generic workspace renderer

The renderer loads a workspace descriptor and maps widget types to React
components.

Widget component examples:

- `MetricStripWidget`
- `LaunchBriefWidget`
- `WorkQueueWidget`
- `AgentFleetWidget`
- `WorkflowReadinessWidget`
- `IntegrationReadinessWidget`
- `ReviewGateWidget`
- `SystemReadinessWidget`
- `CustomTableWidget`

Vet-specific visuals should be implemented as widget configuration and labels,
not a global route.

### Main Control Center

The existing main AgentProvision dashboard should show a compact
`Installed Workspaces` panel:

- enabled workspace packs
- readiness status
- open work count
- setup blockers
- link to each workspace

This keeps the core dashboard generic while still surfacing vertical activity.

## Veterinary Pack Migration

Move the current vet dashboard content into the first workspace pack:

Pack: `vet-practice`

Widgets:

- `launch_brief`
  - Dr. Angelo, Dr. Brett, locations, initial meetings
- `daily_work_queue`
  - owner requests, triage, SOAP, billing, inventory, reputation, ops
- `file_packet_flows`
  - Drive/OneDrive packet requirements
- `review_gates`
  - staff, DVM, manager, Dr. Brett approval gates
- `agent_fleet`
  - Luna Supervisor, Concierge, Front Desk, Triage, SOAP, Billing,
    Inventory, Reputation, Ops, PMS Operator
- `system_readiness`
  - Drive, OneDrive, PMS prep, scribe prep
- `specialist_referral_lane`
  - Dr. Brett cardiology loop

Canonical route:

- `/workspaces/vet-practice`

Compatibility:

- `/practice` redirects to `/workspaces/vet-practice`
- if the pack is not installed, show a 404 or setup prompt, not a vet page
- define a sunset policy once real tenant links no longer depend on `/practice`

## Custom Workspace Builder Later

Custom workspaces are not part of the MVP. After the workspace registry is
stable and at least two native packs have proven the model, add tenant-authored
workspaces.

Future tables:

- `custom_workspaces`
- `custom_workspace_widgets`
- `custom_workspace_permissions`

Builder capabilities:

- choose layout
- add widgets from generic primitives
- bind widgets to agents, workflows, saved searches, integrations, metrics
- set role visibility
- publish draft to production

This is the ERP/CRM-style extension point, but it should not be built until the
native pack abstraction is proven.

Builder safety constraints:

- no raw SQL widgets in tenant-authored workspaces
- no unrestricted arbitrary API composition
- widgets must bind to declared, scoped providers
- every provider enforces tenant and user access server-side
- custom widgets use allowlisted data sources and field projections

## Rollout Phases

### Phase 0 - Stop the Hardcode

- Mark the current vet dashboard PR as prototype / draft only
- Do not merge a permanent hardcoded `/practice` implementation
- Keep useful widget payload/test ideas

### Phase 1 - Registry Foundation

- Add workspace pack registry service
- Add tenant workspace install model and migration
- Add workspace routes
- Add tests for tenant isolation and install visibility
- Seed core workspace/control center as always-enabled
- Add feature flags for native packs and registry sidebar rollout
- Define the `WidgetPayload` envelope and provider contract

### Phase 2 - Frontend Shell

- Add `/workspaces` and `/workspaces/:slug`
- Add dynamic Workspaces sidebar group
- Add generic widget renderer and first reusable widget components
- Add installed workspaces panel to the main control center

### Phase 3 - Vet Pack

- Convert vet dashboard read model into `VetWorkspaceProvider`
- Register `vet-practice` pack
- Install the pack during vet tenant provisioning
- Move `/practice` to compatibility redirect
- Keep PMS as "Practice Software Prep" inside the vet pack

### Phase 4 - Non-Vet Validation Pack

- Add a lightweight `sales-crm` native pack stub
- Use only generic primitives: accounts/deals as queue rows, follow-ups,
  approvals, workflow readiness, and integration readiness
- The goal is to prove the registry is not shaped only by veterinary needs

### Phase 5 - Governance and Setup UX

- Add workspace install RBAC checks
- Add setup states for missing agents/workflows/integrations
- Add audit log entries for workspace install/update/disable
- Add typed widget empty/error/missing-permission states
- Keep only pack `version` and install audit in MVP; defer ALM-style rollback

### Phase 6 - Custom Boards

- Add custom workspace CRUD
- Add widget library and layout persistence
- Add publish/rollback for workspace versions
- Add tenant-scoped export/import of workspace definitions
- Do this only after vet and sales native packs prove the model

## Acceptance Criteria

- A tenant without the vet pack does not see vet navigation or vet widgets
- A vet tenant sees `Vet Practice` under dynamic Workspaces
- `/workspaces/vet-practice` renders the vet workspace from a registered pack
- `/practice` redirects only when the vet pack is installed
- Main dashboard shows installed workspace summaries without becoming vet-specific
- Every workspace query is tenant-scoped
- Missing integrations are displayed as setup blockers, not live capabilities
- PMS remains a future/system-readiness item until computer-use integration is approved
- Tests cover pack visibility, tenant isolation, route gating, and widget rendering
- Tests cover disabled-pack access, RBAC visibility, widget no-data/error states,
  and `/practice` alias behavior
- `GET /workspaces` returns metadata/readiness summaries only, never heavy
  widget payloads
- A non-vet pack stub proves the abstraction does not depend on veterinary
  concepts

## Risks

- Overbuilding a generic workspace builder too early
- Duplicating workflow/agent readiness logic in every pack
- Letting pack metadata imply capabilities that are not actually connected
- Making sidebar load slow by blocking on heavy widget payloads
- Mixing vertical-specific concepts into the core schema
- Leaking installed workspace capabilities across tenants through shared caches
- Allowing custom workspaces to become unrestricted data access

## Risk Controls

- Start with code-defined native packs, not a full builder
- Keep widget payload endpoints lazy
- Use shared readiness helpers for agents/workflows/integrations
- Keep setup states explicit
- Add pack-level tests before adding more verticals
- Keep PMS and other system-specific concepts inside their pack providers
- Feature-flag rollout by tenant and pack
- Use provider contracts instead of raw data access in custom workspaces

## Open Questions

- Should the current vet PR be closed and replaced, or refactored in-place?
- Should the compatibility `/practice` route have a date-based sunset or remain
  indefinitely as a customer-facing alias?
- Should the second native pack be `sales-crm`, or is there a more urgent
  non-vet tenant to validate against?

## Reviewer Feedback Incorporated

### Luna

- Keep the core platform vertical-neutral.
- Do not merge the hardcoded `/practice` implementation as final.
- Enforce tenant and RBAC isolation on sidebar entries, routes, and widget
  payloads.
- Add explicit widget states for setup, missing permission, no data, errors,
  and unsupported features.
- Treat PMS as vet-pack-specific future readiness, not a global core concept.
- Feature-flag rollout by tenant and pack.

### Claudia

- Use user-facing `Workspaces`, not `Dashboards`, for ERP/CRM-style operating
  surfaces.
- Keep packs as composition over existing primitives, not mini-app frameworks.
- Use typed Python native packs first.
- Define `WidgetPayload` before implementation.
- Use stable slug/key bindings instead of UUID bindings.
- Defer custom workspace CRUD, ALM-style rollback, export/import, and builder
  features until vet plus one non-vet native pack prove the abstraction.
