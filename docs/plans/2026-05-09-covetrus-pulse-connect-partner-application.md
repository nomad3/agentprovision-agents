# Plan — Covetrus Pulse Connect Partner Application + Minimum-Viable Adapter

**Owner:** Simon (application) + integration-scaffolding sub-agent (adapter scaffold)
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`) and every future VMG tenant
**Why:** Pulse is the system of record. The 2026-05-09 research (PR #319) confirmed Covetrus Connect is a real partner program with public application + ~6-8wk approval cycle. Without this, Pet Health Concierge can't be record-aware (Herriot replacement), Multi-Site Revenue Sync stays placeholder, and DVM-production / vaccine-compliance dashboards are blocked.

## Goal

Submit Simon's Covetrus Connect application AND ship the minimum-viable adapter scaffold so that the moment partner credentials arrive (T+6-8wk), three read-only flows light up the same day with no further engineering.

## Deliverables

1. **Application packet** — pre-filled form values + outreach email Simon can paste, plus a follow-up cadence (T+0 form, T+2d email, T+1wk Otto reference call, T+4wk check-in if no reply).
2. **Integration registry entry** for `covetrus_pulse` (auth_type='oauth_partner', credential schema: `client_id`, `client_secret`, `practice_id`, `environment` (sandbox|prod)).
3. **MCP tools** in `apps/mcp-server/src/mcp_tools/covetrus_pulse.py`:
   - `pulse_get_patient(patient_id, location_id?)` — vaccines, current Rx, allergies, weight history, diagnoses
   - `pulse_list_appointments(date_range, location_id?)` — schedule + completed visits
   - `pulse_query_invoices(date_range, location_id?, limit?)` — billing line items
4. **HMAC-or-OAuth signing helper** modeled after the BrightLocal adapter (PR #324) — once we know which auth flow Pulse Connect actually uses (research-blocked until partner intake; scaffold both branches).
5. **Activation gate** — workflows referencing these tools refuse to run until the tenant has Pulse credentials configured. The Pet Health Concierge persona already references Pulse hooks as TODO.
6. **Tenant config: `pulse_practice_id`** — even with one Pulse instance, queries filter by `location_id ∈ (anaheim | buena_park | mission_viejo)`. Each tenant configures their list of location IDs in the integration setup UI.
7. PR on `feat/covetrus-pulse-connect-adapter`, assigned to nomad3, no AI credit lines.

## Scope — IN

- Read-only patient + appointment + invoice scopes only, until Phase 2
- Signing flow scaffolded both as OAuth client_credentials AND as HMAC (BrightLocal-style), feature-flagged; final flow picked at partner intake
- Per-tenant credentials via existing `integration_credentials` (Fernet-encrypted)
- Cache layer (Redis 4h TTL, same pattern as BrightLocal)
- Full unit-test suite with mocked HTTP

## Scope — OUT

- Write scopes (record_observation back into Pulse) — Phase 2
- Webhook subscription / event-driven sync — Phase 2
- HIPAA / BAA — N/A for vet, but contractually flow CCPA terms (CA tenant) per the research doc

## Steps

1. **Application packet (Simon, day 0):** Pre-fill the partner registration form at `https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/`. Form fields per the research doc: vendor=AgentProvision, product category=AI Workflow Automation, integration type=Bi-Directional, practice count=3 (Animal Doctor SOC as design partner), current user base=Members of VMG (~2,000-owner network adjacent).
2. **Email outreach:** `support_pulse@covetrus.com` requesting sandbox URL, fee schedule, SOC 2 Type II under NDA, and confirmation that Connect API exposes patient/appointment/invoice/inventory/SOAP scopes. Otto, Chckvet, SmartFlow pages confirm partner-visible scopes — name them in the email as the precedent.
3. **Otto reference call (Simon, T+1wk):** otto.vet/contact — 20 min on partner experience, fee structure, sandbox cycle.
4. **Adapter scaffold (engineering, week 1):**
   - Mirror BrightLocal's structure (`apps/mcp-server/src/mcp_tools/brightlocal.py` is the closest analog)
   - 3 MCP tools listed above + their unit tests
   - Both HMAC + OAuth branches behind a `PULSE_AUTH_FLOW` env var (default `oauth`, override `hmac` if intake says otherwise)
   - Activation gate via `TOOL_INTEGRATION_MAP` in `apps/api/app/services/integration_status.py`
   - Integration registry entry with both credential field sets
5. **Mock-Pulse fixtures:** Snapshot fake Pulse responses based on Otto's published payload examples + Covetrus's general API conventions. Use them in unit tests so the adapter works end-to-end before real credentials land.
6. **Multi-Site Revenue Sync workflow update:** Replace the placeholder `query_data_source covetrus_pulse` step (currently just hits `query_data_source` with name='covetrus_pulse') with `pulse_query_invoices(date_range='1d', limit=500)`. Idempotent migration 117.
7. **Pet Health Concierge persona:** Replace the inline TODO Pulse-hooks block with a real instruction: "When the client is authenticated, call `pulse_get_patient(patient_id)` first; surface allergies + current Rx in your reply; if Pulse is unreachable, fall back to the unauthenticated triage flow."

## Definition of Done

- ✅ Application + outreach packet drafted as a runbook Simon executes manually
- ✅ Adapter scaffold + 3 MCP tools + unit tests green in CI
- ✅ Integration registry entry visible in `/integrations`
- ✅ Multi-Site Revenue Sync workflow + Pet Health Concierge persona reference real tools
- ✅ Mock-Pulse fixtures cover the patient/appointment/invoice happy paths
- ✅ Migration 117 idempotent, self-records, tenant-scoped (per PR #324 review pattern)
- ✅ PR `feat/covetrus-pulse-connect-adapter`, assigned to nomad3, no AI credit lines

## Risks

- Partner program may demand a fee or revenue-share — research doc flagged this as unverified. Adapter ships regardless.
- Pulse Connect may use a different auth scheme than what we scaffolded. Both branches reduce risk; intake confirms which.
- 6-8wk timeline is Covetrus's stated SLA; could slip.

## Test plan

- Unit: each tool against mocked Pulse responses
- Integration: end-to-end Multi-Site Revenue Sync workflow with mocked Pulse responses → confirm Luna delivers a structured morning briefing
- Manual (when partner credentials arrive): connect creds in `/integrations`, run the workflow once, inspect WhatsApp delivery

## Cross-references

- Research: `docs/research/2026-05-09-covetrus-pulse-api-research.md`
- Adapter pattern: `apps/mcp-server/src/mcp_tools/brightlocal.py` (PR #324)
