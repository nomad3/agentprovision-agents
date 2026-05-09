# Runbook — Covetrus Connect Partner Application (Simon-executed)

**Date:** 2026-05-09
**Owner:** Simon
**Tenant in scope:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`) and every future VMG tenant
**Driving plan:** [`2026-05-09-covetrus-pulse-connect-partner-application.md`](2026-05-09-covetrus-pulse-connect-partner-application.md)
**Research:** [`docs/research/2026-05-09-covetrus-pulse-api-research.md`](../research/2026-05-09-covetrus-pulse-api-research.md)

This is the manual outreach packet that lights up the engineering scaffold.
The adapter (3 MCP tools, mock-Pulse fixtures, integration registry entry,
activation gate, migration 118 wiring the Multi-Site Revenue Sync workflow)
ships in the same PR — Simon executes the steps below in parallel so
partner credentials arrive on a system that's already wired and tested.

---

## Cadence — at-a-glance

| When | Action | Owner |
|---|---|---|
| **T+0 (today)** | Submit Covetrus Connect partner registration form | Simon |
| **T+0 (today)** | Email `support_pulse@covetrus.com` with the canned ask below | Simon |
| **T+0 (today)** | Have Angelo screenshot Pulse → Settings → Integrations (Option-B free probe) | Angelo |
| **T+2d** | Follow-up email if no acknowledgement | Simon |
| **T+1wk** | Otto reference call (otto.vet/contact) | Simon |
| **T+4wk** | Status check-in if no partner-team contact | Simon |
| **T+6-8wk** | Partner credentials arrive → flip `PULSE_AUTH_FLOW` to confirmed value, paste creds in `/integrations` for Animal Doctor SOC | Simon + Engineering |

---

## Step 1 — Submit the Covetrus Connect registration form

**URL:** [https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/](https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/)

Pre-filled values (from research doc):

| Field | Value |
|---|---|
| Vendor name | AgentProvision (a Wolfpoint product) |
| Website | https://agentprovision.com |
| Contact name | Simon Aguilera |
| Contact email | saguilera1608@gmail.com |
| Phone | (Simon's preferred contact number) |
| Product category | **Client Communication** + **Workflow Optimization** (both apply; pick whichever the form allows — research doc identified these as the closest matches across the 23 options) |
| Product description | "AI workflow automation platform purpose-built for veterinary practices. Pet Health Concierge replaces front-desk triage with a record-aware AI that grounds every reply in the Pulse chart. Multi-Site Revenue Sync delivers daily per-location revenue rollups to the practice owner via WhatsApp." |
| Integration type | **Bi-Directional** (read scopes ship Phase 1; write scopes Phase 2) |
| Current user base | "Members of VMG (~2,000 private practice owners) — Animal Doctor SOC is our design-partner customer for the vet vertical." |
| Number of practices already using Covetrus systems | **3** (Anaheim, Buena Park, Mission Viejo via Animal Doctor SOC, single Pulse instance) |

**Other tips:**
- If asked for a demo / video, link the AgentProvision marketing site or paste the Animal Doctor SOC pitch deck (`docs/pitch/`).
- If asked which Covetrus PMS you target, say **Pulse** explicitly (the Connect program covers Pulse + AVImark + ImproMed but Pulse is our scope).

---

## Step 2 — Email outreach to support_pulse@covetrus.com

Send from Simon's address. Subject: **"AgentProvision — Covetrus Connect partner enrollment + Pulse Connect API scope confirmation"**.

```
Hi Covetrus Pulse team,

I'm Simon Aguilera, founder of AgentProvision (https://agentprovision.com).
We just submitted the Covetrus Connect Technology Integration Partner
Program registration form for our veterinary AI workflow platform. I'd
appreciate a quick confirmation of receipt and answers to a few specifics
so we can scope our integration cleanly:

1. Sandbox / developer-environment URL — we'd like to start mock-testing
   our adapter against a Pulse sandbox before partner credentials arrive.
   Our research found the live host at api.covetrus.com but the sandbox
   surface isn't public. Is there a sandbox we can be granted access to
   ahead of full partner enrollment?

2. Partner program economics — could you share whether the Connect
   program has a flat partner fee, revenue share, or is free? We want to
   model this into our pricing for the AnimalDoctorSOC pilot before we
   sign the Integrated Partner Agreement.

3. SOC 2 Type II report under NDA — happy to sign your standard NDA;
   our pitch to VMG members emphasizes SOC 2-aligned data handling and
   we'd like to be able to reference Covetrus's posture truthfully.

4. Pulse Connect API scopes — could you confirm the program exposes the
   following scopes to approved partners (read at minimum, ideally
   write at Phase 2)?
     - patients (signalment, vaccines, current meds, allergies,
       weight history, diagnoses, last-visit summary)
     - appointments (schedule + completed visits)
     - invoices + line items (per-location revenue rollup)
     - inventory (Phase 2)
     - SOAP notes (Phase 2)

   Our reference points are Otto, Chckvet, SmartFlow, and Anipanion,
   which all advertise these scopes on their Pulse-integration product
   pages — we want to match parity, not exceed it.

5. Designated technical / partnerships contact — once the application is
   reviewed I'd like a single point of contact for the credential issue
   + integration verification stages.

Our design-partner customer is The Animal Doctor SOC (3 hospitals on a
single Pulse instance: Anaheim / Buena Park / Mission Viejo) and our
strategic distribution channel is VMG (~2,000-owner network). I'm happy
to set up a 30-minute call at your convenience.

Thanks,
Simon Aguilera
AgentProvision
saguilera1608@gmail.com
```

**Cc:** Angelo Castillo (`<angelo's email>`) — gives Covetrus a customer
reference inside the same thread.

---

## Step 3 — Option-B free probe (Angelo, today)

Have Angelo log into the Animal Doctor SOC Pulse instance and screenshot
**Settings → Integrations** (and any "API Tokens" / "Developer" sub-page).
If a self-serve API token tab exists, that unblocks **read-only** scopes
without partner approval — even if the breadth is limited, it lets the
Pet Health Concierge ship in record-aware mode immediately on launch
day rather than waiting 6-8 weeks for the partner SLA.

If the screenshot shows nothing, we lose nothing — partner-program path
is the primary plan regardless.

Save the screenshot under `docs/data/animal-doctor-soc/`.

---

## Step 4 — Otto reference call (T+1wk)

Use Otto's contact form: [https://otto.vet/contact/](https://otto.vet/contact/)
Backup: hello@otto.vet, plus LinkedIn outreach to Otto's CEO/CTO.

Suggested message:

```
Hi Otto team,

I'm Simon Aguilera, founder of AgentProvision — we're building a vet-
practice AI platform and the Animal Doctor SOC (3 hospitals on Pulse,
~2,000-member VMG network) is our design partner. We're behaviorally
adjacent to your front-desk + client-communication suite (we're focused
on AI agents for triage + multi-site revenue rollups), and we just
submitted our Covetrus Connect partner application.

Before we sign the Integrated Partner Agreement, would you be open to
a 20-min reference call about your partner experience? Specifically:
1. Real timeline from registration to credential delivery (Covetrus
   says 6-8wk SLA — does that match reality?)
2. Fee structure / revenue share, if you can share publicly
3. Sandbox access — do they issue dev creds before signature, or only
   after?
4. Webhook contract for client / appointment / invoice events

Happy to swap notes on the vet AI space — we're not a head-on
competitor, we sit downstream of the receptionist surface.

Thanks,
Simon
```

If they decline, no problem — Anipanion or Chckvet are next-best
references (also published Pulse partners).

---

## Step 5 — Follow-up cadence

- **T+2d:** If no `support_pulse@covetrus.com` acknowledgement, bump the
  thread once. Single bump only — don't chase.
- **T+4wk:** If no partnerships-team contact and we're still inside the
  6-8wk SLA, friendly status check on the existing thread.
- **T+8wk:** If we've crossed the SLA without contact, escalate to
  Covetrus's main marketing contact (LinkedIn outreach to a Covetrus
  Director-of-Partnerships title) and CC the original support thread.

---

## Step 6 — Credential intake (T+6-8wk, when the partner team contacts us)

When Covetrus issues the OAuth `client_id` + `client_secret` + `practice_id`:

1. Confirm with their tech contact whether the auth flow is **OAuth2
   client_credentials** (default in our scaffold) or **HMAC-signed query
   strings** (BrightLocal-style fallback).
2. If HMAC: set `PULSE_AUTH_FLOW=hmac` in the API + MCP server env
   (api-secrets ConfigMap / Helm values) and redeploy.
3. If OAuth (default): no env change needed.
4. Open AgentProvision → `/integrations` → **Covetrus Pulse** card and
   paste:
   - `client_id`
   - `client_secret`
   - `practice_id`
   - `environment`: `sandbox` first (test against the workflow), then
     swap to `prod`
   - `location_ids`: `anaheim,buena_park,mission_viejo`
5. Run the **Multi-Site Revenue Sync** workflow once manually (it's
   already wired to `pulse_query_invoices` via migration 118) and
   confirm Luna delivers a structured morning briefing to Angelo's
   WhatsApp.
6. Verify the **Pet Health Concierge** persona surfaces a real Pulse
   chart on the next authenticated client interaction (we ship the
   persona pre-wired to call `pulse_get_patient` first).

---

## Cross-references

- Plan: [`2026-05-09-covetrus-pulse-connect-partner-application.md`](2026-05-09-covetrus-pulse-connect-partner-application.md)
- Research: [`../research/2026-05-09-covetrus-pulse-api-research.md`](../research/2026-05-09-covetrus-pulse-api-research.md)
- Adapter source: `apps/mcp-server/src/mcp_tools/covetrus_pulse.py`
- Adapter tests: `apps/mcp-server/tests/test_covetrus_pulse_tool.py`
- Mock fixtures: `apps/mcp-server/tests/fixtures/covetrus_pulse_fixtures.py`
- Activation gate: `apps/api/app/services/integration_status.py`
  (`TOOL_INTEGRATION_MAP` entries `pulse_*` → `covetrus_pulse`)
- Integration registry: `apps/api/app/api/v1/integration_configs.py`
  (`covetrus_pulse` entry, `auth_type='oauth_partner'`)
- Multi-Site Revenue Sync wiring: `apps/api/migrations/118_pulse_revenue_sync_wiring.sql`
- Pet Health Concierge persona update: same migration, second UPDATE block
