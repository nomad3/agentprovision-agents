# Plan — iMessage / SMS Integration (Twilio)

**Owner:** Integration scaffolding + design
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`)
**Why:** Dr. Castillo explicitly preferred iMessage / SMS over WhatsApp for client-facing comms (US market). The Pet Health Concierge persona already references iMessage/SMS as a roadmap channel. This unlocks the second-most-requested channel surface for the Harriet replacement.

## Goal

Ship an SMS integration via Twilio that lets the Pet Health Concierge agent handle inbound and outbound text messages. Document the iMessage path (Apple Messages for Business) but do NOT build it (gated behind enterprise approval).

## Deliverables

1. `docs/plans/2026-05-09-imessage-sms-integration.md` (this file) — design + scope
2. `apps/mcp-server/src/mcp_tools/sms.py` — MCP tools: `send_sms`, `list_sms_threads`, `read_sms`
3. `apps/api/app/api/v1/twilio_webhook.py` — public webhook endpoint receiving Twilio inbound SMS
4. Migration adding `sms_threads` table OR re-using `chat_sessions` with `channel='sms'` (decide which based on existing `chat_sessions.channel` column conventions)
5. Integration registry entry for `twilio_sms` (auth_type='manual', credentials: account_sid, auth_token, messaging_service_sid OR from_number)
6. Wiring in `agent_router` so inbound SMS messages from a Twilio phone number route through the Pet Health Concierge agent
7. PR on branch `feat/twilio-sms-integration` assigned to nomad3

## Scope — IN

### SMS via Twilio
- Outbound: any agent calling `send_sms` MCP tool with `to`, `body`, optional `from_number_override`
- Inbound: Twilio webhook posts to `/api/v1/integrations/twilio/inbound`. Verify signature using `X-Twilio-Signature`. Resolve tenant by `To` number, resolve / create chat_session keyed on `From`, dispatch to Pet Health Concierge.
- Multi-tenant: each tenant configures its own Twilio creds + clinic phone number(s)
- Per-message audit: record send + receive in `chat_messages` with `channel='sms'`, source IP / Twilio MessageSid in context

### Apple Messages for Business (iMessage)
- Document only. Apple requires enterprise approval through `register.apple.com/business/messages`, can take 4-12 weeks. Note the application URL + estimated timeline in the design doc. Do NOT scaffold.

## Scope — OUT

- iMessage actual integration (gated)
- MMS / media attachments — defer to v2
- 10DLC compliance / Twilio Verify — flag in the design but don't ship in this PR
- Voice / RCS — out of scope

## Steps

1. **Architecture decision:** chat_sessions table reuse vs new sms_threads. Read `apps/api/app/models/chat.py` to see how `channel` is used currently. Reuse if `channel='sms'` is a clean addition.
2. **Twilio webhook signature verification:** use `twilio.request_validator.RequestValidator` (pip dep `twilio`). Reject unsigned requests.
3. **Tenant resolution by `To` number:** integration_credentials should store `phone_number` per tenant. Lookup → tenant_id.
4. **Chat session resolution by `From` number:** same `(tenant_id, channel='sms', remote_id=From)` key. Reuse if exists, else create.
5. **Dispatch:** route through existing `route_and_execute` path with `agent_slug='pet_health_concierge'` and channel hint.
6. **Outbound MCP tool:** `send_sms(to, body, tenant_id)` — looks up tenant's Twilio creds, calls Twilio REST API.
7. **Migration:** if reusing chat_sessions, add `channel` enum value if not already present. Otherwise minimal new table.
8. **Integration registry entry:** add `twilio_sms` to the integrations registry with credential keys: `account_sid`, `auth_token`, `phone_number` (the clinic number that receives inbound SMS).
9. **Tests:** unit test for signature verification, unit test for tenant-resolution-by-To, integration test for the inbound webhook path stubbing Twilio + agent dispatch.
10. **PR:** `feat/twilio-sms-integration` to main, assigned to nomad3, no AI credit lines.

## Inputs / blockers

- **Need from Simon (or direct from Angelo when he onboards):** Twilio credentials. The PR ships the integration scaffolding — actual credentials get added per-tenant via the integrations UI.
- 10DLC registration if launching to actual US clients — flag in PR but don't gate the merge on it.

## Definition of Done

- ✅ Inbound SMS to a Twilio number with valid signature → reaches Pet Health Concierge → response sent back via Twilio
- ✅ Signature verification rejects unsigned requests
- ✅ Multi-tenant: same code serves both AgentProvision and Animal Doctor SOC
- ✅ Integration registry shows `twilio_sms` card; credentials configurable through the integrations UI
- ✅ Unit tests pass; CI green; PR assigned to nomad3
- ✅ Apple Messages for Business path documented separately (link to `register.apple.com/business/messages`, estimated timeline, prerequisites)

## Risks

- 10DLC enforcement is real — without registration, US carriers may block traffic. Document but don't block.
- Twilio's signature validator requires the FULL public URL — make sure the cloudflared tunnel URL is what gets validated, not the in-cluster `http://api:8000`.
- `twilio` Python pkg adds runtime weight — keep it in `apps/api/requirements.txt` only, don't load on every chat path.

## Test plan

- `curl -X POST -H 'X-Twilio-Signature: ...' https://agentprovision.com/api/v1/integrations/twilio/inbound` with valid signed test payload → 200 + agent response
- Unsigned `curl` → 403
- Outbound `send_sms` MCP tool with a test number → message logged in `chat_messages` with `channel='sms'`

---

## Implementation notes (2026-05-09 PR)

### Architecture decision: reuse `chat_sessions`, no new table

Initial inspection of `apps/api/app/models/chat.py` showed `ChatSession` has
`source` (free-form, default `"native"`) and `external_id` columns —
WhatsApp already uses `source="whatsapp"` + `external_id="whatsapp:<jid>"`
(see `whatsapp_service._process_through_agent`). SMS reuses the same
pattern with `source="twilio_sms"` + `external_id=f"twilio_sms:{from_number}"`.

For audit trail, `channel_accounts` (`channel_type="sms"`) and
`channel_events` already accept any free-form `channel_type` — we don't
need migrations. One row per tenant SMS line in `channel_accounts`,
one row per inbound + outbound message in `channel_events`.

**No DB migration is shipped in this PR.**

### Twilio API endpoints wired

- **Outbound:** `POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json`
  with HTTP Basic auth (`account_sid:auth_token`) and form fields
  `From`, `To`, `Body`. Used by `_send_twilio_sms` in
  `app/api/v1/twilio_webhook.py`.
- **Inbound:** Twilio Console webhook → our endpoint
  `POST /api/v1/integrations/twilio/inbound` (form-encoded), signature
  in `X-Twilio-Signature` header.
- **Lookup, MMS, Verify** are *out* of scope.

### Files shipped

- `apps/api/app/api/v1/twilio_webhook.py` — public inbound endpoint +
  three internal helpers (`/internal/send`, `/internal/threads`,
  `/internal/thread/{id}`) used by the MCP tools.
- `apps/api/app/api/v1/integration_configs.py` — `twilio_sms` registry card
  (account_sid, auth_token, phone_number).
- `apps/api/app/api/v1/routes.py` — mount the router at root so
  `/api/v1/integrations/twilio/inbound` is the public URL.
- `apps/api/requirements.txt` — `twilio>=9.3.0` for `RequestValidator`.
  The webhook also has a pure-Python HMAC-SHA1 fallback so unit tests
  can run on minimal images.
- `apps/api/tests/test_twilio_webhook.py` — 11 unit tests covering
  signature verification (valid + tampered + wrong-token + missing
  signature), phone normalization, and tenant resolution by `To`.
- `apps/mcp-server/src/mcp_tools/sms.py` — `send_sms`,
  `list_sms_threads`, `read_sms`. All three call back into the API at
  `/api/v1/integrations/twilio/internal/...` so the Twilio auth_token
  never leaves the API pod.
- `apps/mcp-server/src/mcp_tools/__init__.py` — register the module.
- `apps/mcp-server/tests/test_sms_tool.py` — 8 tests verifying the MCP
  tools never call Twilio directly and propagate API errors.

### Multi-tenant routing — by To number

`_resolve_tenant_for_to_number` scans every active `twilio_sms`
integration_config across all tenants, decrypts each one's
`phone_number` credential, and returns the matching tenant. This is
linear in the number of tenants with SMS — fine for the foreseeable
scale (<1000 tenants); if it ever grows, an index on
`integration_credentials.encrypted_value` won't help (it's
ciphertext) — switch to caching `phone_number → tenant_id` in
`channel_accounts.phone_number` (already populated by
`_get_or_create_channel_account`) and querying that first.

### Pet Health Concierge agent slug resolution

`_pick_agent` tries `Agent.name ILIKE 'Pet Health Concierge'` first
(matches the agent already deployed on the Animal Doctor SOC tenant).
Tenants without that agent (e.g. AgentProvision itself) fall back to
the first agent on the tenant. This matches the existing pattern in
`whatsapp_service._process_through_agent` (which prefers Luna), just
with a different preference order — SMS messages from US clients are
expected to be vet-related, not platform admin.

---

## iMessage / Apple Messages for Business — roadmap (NOT in this PR)

### Why deferred

Apple Messages for Business (the only legitimate way for a business to
send/receive iMessage from a brand identity rather than a personal
phone) requires:

1. Enrollment in **Apple Business Register** at
   <https://register.apple.com/business/messages> — free but gated.
2. Apple's review of the business account (typically 4-12 weeks).
3. Selecting a **Messaging Service Provider (MSP)** — Twilio,
   Sendbird, LivePerson, Sinch, Zendesk, Quiq, etc. — that proxies
   iMessage between Apple and our webhook. Twilio's iMessage product
   is currently in limited preview as of 2026-05.
4. Per-MSP additional vetting (Twilio requires their own KYC layer
   even after Apple approves).

Until Apple approves the Animal Doctor SOC business identity, the
iMessage path can't be built (no sandbox; the test environment also
requires approval). SMS via Twilio works *today* in the US and is
the right channel to ship first.

### When it lands

When Apple Business Register approves us, the implementation surface
is small:

- New integration card `apple_messages_for_business` with credentials
  `business_id`, `msp_provider` (twilio | sendbird | …), MSP-specific
  api_key, plus the same `phone_number` proxy.
- New webhook endpoint `/api/v1/integrations/imessage/inbound`. The
  payload schema differs by MSP — Twilio reuses their existing
  Messaging Webhook with a different `MessagingServiceSid`, while
  Sendbird/LivePerson have their own JSON envelopes.
- `send_sms` MCP tool grows an `imessage_first: bool = True`
  argument: when both channels are configured, attempt iMessage and
  fall back to SMS on a per-recipient basis (Apple exposes a
  capability check via the MSP).
- Same `chat_sessions.source` pattern with a new value
  `apple_messages_for_business`.

The webhook signature verification will differ per MSP — Twilio is
the same algorithm we already implemented; Sendbird uses HMAC-SHA256
on a different payload shape. Plan to implement Twilio's iMessage
first (lowest delta from the SMS code in this PR).

### Application checklist for whoever submits to Apple

1. Register an Apple Business ID (DUNS number required).
2. Provide a customer support email + phone reachable during business hours.
3. Pick MSP — recommend Twilio for code reuse with this PR.
4. Submit screenshots / video of the conversational experience as
   it'll appear in the Messages app (avatar, business name, opening
   greeting).
5. Wait. Plan for 4-12 weeks; some accounts have reported 6-month
   waits. Don't gate any other roadmap items on this.

