# WhatsApp → official Business Cloud API — migration plan

**Date:** 2026-06-04
**Owner:** Simon Aguilera
**Reviewers (full council):** superpowers, Codex-5.5, Luna
**Status:** plan — **full council complete 2026-06-04 (superpowers + Codex-5.5 + Luna, all approve-with-changes; all findings folded in)**. Luna's product lens added §5a (the migration changes the product contract). Date-sensitive figures (§10) still MUST be re-confirmed against Meta's live rate card before any number is committed to billing.
**Builds on (design only):** `docs/plans/2026-05-20-whatsapp-waha-migration-design.md` **specified** the `AbstractWhatsAppBackend` interface, the `channel_accounts.backend` column, and a webhook-receiver shape — but **none of it was ever implemented** (verified 2026-06-04: no `apps/api/app/services/whatsapp_backends/` package, no `channel_accounts.backend` column, migration head is **157**; the WAHA doc predicted migration 143 for `backend`, but 143 is actually `creative_reflections_optin`). So this plan **builds the abstraction the WAHA design specified but never shipped**, then implements the Cloud API backend against it. Where this doc says "reuse the WAHA seam," read it as **"construct that seam (net-new) + extract a `NeonizeBackend` from the current 2,684-line `whatsapp_service.py`"** — the P0 effort estimate (§6) absorbs that construction.

> ⚠️ **Every pricing/rule figure here is date- and version-sensitive** (Graph API ~v23.0; rates revised ~quarterly, last Jan 1 + Apr 1 2026; Chile moved to CLP billing Apr 1 2026; Mar-2026 preemptive enforcement). The council review **must re-confirm against Meta's live WhatsApp Manager rate card + first-party docs** before any number is committed to billing. Several figures (esp. Chile rates, throughput, the request_code/register payloads) are single- or secondary-sourced.

## 1. Thesis

Move Luna's WhatsApp off the reverse-engineered **neonize/whatsmeow** stack onto Meta's **official WhatsApp Business Cloud API**.

**Why now:** neonize is a perpetual firefight — silent socket disconnects, QR re-pair races, SQLite session corruption. We shipped PR #765 (validated session backups + clean-shutdown drain) and the fire-and-forget delivery rebuild *solely to paper over* these. It also carries **existential account-ban risk**: it pairs a consumer WhatsApp account against Meta's ToS — a latent risk for every tenant. The Cloud API is Meta-hosted: **no socket to go stale, no session blob to corrupt, no QR**, and it's the **only sanctioned path for a SaaS**.

**The cost of the move (honest):** the Cloud API imposes the **24-hour customer-service window** — outside 24h of a user's last inbound, Luna **cannot send free-form text at all**; she may only reach the user via a **pre-approved template**, and marketing templates are **billed per delivery**. That's a real behavior loss (no ad-hoc proactive outreach) and a new per-message cost line where neonize was free.

**Verdict shape:** strong **yes** on reliability + sanctioned-path + scale, **gated** on accepting the 24h/template constraint and a modest, tenant-billed per-message cost.

## 2. Cost model

**Model (per-message, since Jul 1 2025; per-conversation billing deprecated):** billed per **delivered template**, rate = f(template **category**, recipient **country**). Four categories:
- **Marketing** — always paid, priciest, not volume-tiered.
- **Utility** — paid, ~80–90% cheaper than marketing; **free inside an open 24h window**.
- **Authentication** — paid, low, volume-tiered.
- **Service / free-form** — **free + unlimited inside the 24h window** (the old 1,000-free-conversation cap was removed Nov 1 2024).

**Two free windows zero out cost:** the **24h customer-service window** (opens on each user inbound; free-form replies + utility templates free) and the **72h Free-Entry-Point window** from Click-to-WhatsApp ads (every message free). **Real cost concentrates only on business-initiated marketing/auth sends to users with no open window.**

**Representative 2026 rates** (USD, Marketing / Utility / Auth, by recipient country — *verify against live rate card*):

| Country | Marketing | Utility | Auth |
|---|---|---|---|
| US | $0.025 | $0.004 | $0.004 |
| Chile † | $0.0889 | $0.020 | $0.020 |
| Brazil | $0.0625 | $0.0068 | $0.0068 |
| Mexico | $0.0305 | $0.0085 | $0.0085 |
| Colombia | $0.0125 | $0.0008 | $0.0008 |

† Chile is **single-sourced** and moved to CLP local billing Apr 1 2026 — USD-equiv may FX-shift. **Pull the live WhatsApp Manager CSV before contractual modeling.**

**Worked monthly example — a representative Chile tenant (vet/SMB co-pilot = Luna's actual profile):** Luna answers ~all traffic *inside* the 24h window ($0). Proactive sends *outside* the window:
- 3,000 appointment/report-ready pings as **utility** templates ≈ 3,000 × $0.02 = **~$60**
- 2,000-recipient monthly **marketing** re-engagement ≈ 2,000 × $0.0889 = **~$178**
- 500 OTP/**auth** ≈ 500 × $0.02 = **~$10**
- **Tenant total ≈ ~$248/mo**, billed by Meta **directly to the tenant's card** (Tech-Provider model — AgentProvision charges only its SaaS fee, **no per-message markup**, no credit-line risk).

**Modeling rule:** `budget = (business-initiated msgs outside any window) × category rate`; everything in-window is $0.

## 3. Target architecture

Split the single neonize socket into **two HTTP halves** behind an `AbstractWhatsAppBackend` seam (**built here** — see header; the WAHA design specified it but it was never shipped). **The fire-and-forget chat pipeline in the middle is reused verbatim** — verified: `_handle_inbound` already downloads media synchronously inline, and `chat_jobs.run_job_blocking`/`post_user_message` accept a second message source unchanged. The backend only changes *where a message arrives* and *how the reply leaves*.

> **Precedent — `apps/api/app/api/v1/twilio_webhook.py` (687 lines) is the reference implementation.** It already drives a webhook-based inbound channel: validates a provider signature (`_verify_twilio_signature`), resolves tenant by destination number (`_resolve_tenant_for_to_number`), mints/reuses per-tenant `channel_account` rows (`_get_or_create_channel_account` — "mirror the pattern in whatsapp_service"), and dispatches into the **same** `chat_service.post_user_message` pipeline. The Cloud-API receiver (HMAC verify → tenant by `phone_number_id` → normalize → dispatch) is structurally identical — model it on `twilio_webhook.py`, don't reinvent from the neonize side.

**Inbound — webhook receiver (NEW):** `POST /api/v1/whatsapp/cloud-webhook`.
- `GET` handshake echoes `hub.challenge` when `hub.verify_token` matches.
- `POST` validates `X-Hub-Signature-256` = HMAC-SHA256 over the **raw body** keyed by the App Secret (⚠️ re-serializing the JSON breaks the HMAC; the HMAC is keyed by **your App Secret — one secret for the app, not per-tenant**, so the signature proves authenticity but does **not** establish which tenant), returns **200 immediately**, **dedups by `wamid`**, then normalizes `entry[].changes[].value.messages[]` into the same dict shape `MessageEv` produces today.
- **Dedup retention must cover Meta's retry horizon (~7 days), not 24h.** A Redis SET with a 24h TTL lets a >24h-late retry of an already-processed message reprocess. Use a **7-day TTL** (or persist processed `wamid`s in a small table with a bounded daily cleanup). Cost is trivial; correctness is not.
- **Tenant routing (I4):** Cloud API delivers `phone_number_id` in `value.metadata.phone_number_id`. The receiver maps that → `ChannelAccount` **before any auth context exists** (DB lookup on an indexed `phone_number_id`; this is exactly `twilio_webhook.py:_resolve_tenant_for_to_number`). **Unknown `phone_number_id` → still return 200 (never non-200, or Meta retries for ~7 days), then drop.**
- **Codebase seam:** split `whatsapp_service.py:_handle_inbound` (~line 1190) into `_normalize_inbound_event(source) -> InboundMessage` + a neonize-free `_handle_inbound(dict)`. Media is already downloaded synchronously (~line 1228) — **keep the *timing model* (sync, before the turn)**; the *mechanism* is new: neonize FFI `client.download_any` becomes a 2-step `GET /<MEDIA_ID>` → short-lived URL (~15 min) → bearer fetch.

**Outbound — Cloud API sender (NEW):** `POST https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/messages` with a Bearer token.
- Inject a `send_fn` into `_send_reply_or_fallback` (~line 1900): `send_fn` = neonize `client.send_message` **or** an httpx POST to the Cloud API. Both keep the existing **chunking, sent-ID echo-suppression, and event logging**; only the typing/PAUSED-presence tail differs.
- **In-window → `type:text`** free-form; **out-of-window → `type:template`** (name + language + positional params).

**Reused verbatim (the brain):** `_enqueue_turn` (~1705), `_chat_consumer` (~1736), the per-sender queue + capacity gate (global=16, per-sender=4, `WHATSAPP_CHAT_WORKERS=4`), `_run_turn` (~1771) → `chat_jobs.run_job_blocking`, the `create_job → start_job → finish_job` state machine, and `post_user_message`.

**Per-tenant `ChannelAccount` repurposed (not replaced):** add `backend VARCHAR(20) DEFAULT 'neonize'` (the WAHA design *specified* this column but never shipped it — **this migration creates it**; Cloud API = a third value `'cloud-api'`). **Canonical token storage = the Fernet credential vault** (one source of truth, matches every other provider). On `ChannelAccount`, store only **identifiers/metadata**: `waba_id`, `phone_number_id`, `token_expires_at` — these three can even ride the existing `config` JSON column with **zero DDL** (only `backend` arguably wants a real column, for `select_backend` queries). Do **not** add a second `access_token` column that duplicates the vault. **Keep `session_blob` during cutover for rollback.**
- **Replace** `_save/_restore_session_from_db` (~694/813) — SQLite checkpoint/gzip becomes token-validity/refresh; **reuse** the per-account `asyncio.Lock` for token-rotation coordination.
- **Replace** `_socket_heartbeat` (~383) + `_auto_reconnect` (~1126) — there's no socket; liveness becomes webhook `session.status` events / token-expiry re-auth.
- **Guard the neonize-only startup/shutdown hooks (I3).** `restore_connections` (~2629, called from `main.py:184`), `drain_and_shutdown` (~2487, `main.py:239`), and `shutdown` (~2601, `main.py:397`) all run unconditionally at app boot/shutdown and are session-socket-centric. On a `'cloud-api'` account there is no socket to restore or drain — **each must no-op for that backend** (branch on `account.backend`), or a half-migrated boot path throws.
- Per-tenant tokens reuse the **Fernet credential vault** + the internal-token-fetch pattern (`GET /oauth/internal/token/{integration}`, `oauth.py:915`). The public `channels.py` endpoint surface (enable/pair/pair-status/send/logout) is preserved; each dispatches via `select_backend(tenant_id, account_id)`.

## 4. Multi-tenant onboarding — Tech Provider + Embedded Signup

**Pattern:** register AgentProvision as a Meta **Tech Provider (ISV)**, *not* a Solution Partner/BSP. Each tenant connects **their own WABA + number via Embedded Signup** and attaches **their own payment method** → **Meta bills the tenant directly**. AgentProvision charges only its SaaS fee: no per-message markup, no Meta credit-line, no collections/bad-debt risk, WABAs stay portable. This maps 1:1 onto the existing per-tenant credential-vault + per-tenant OAuth architecture.

**Embedded Signup flow:** load the FB JS SDK → `FB.init({appId, version:'v23.0'})` → create an Embedded Signup config → `config_id` → `FB.login({config_id, response_type:'code', override_default_response_type:true, extras:{sessionInfoVersion:'3'}})`. A window `message` listener captures `WA_EMBEDDED_SIGNUP` (`waba_id` + `phone_number_id`); the callback returns an auth **code**. Server-side: exchange the code for the tenant's long-lived **System User token**, persist per-tenant in the Fernet vault, `POST /<WABA_ID>/subscribed_apps`, and register the number (`request_code → verify_code → /register` with a 6-digit PIN). Use a **WABA-level webhook override** so each tenant's inbound routes to our endpoint keyed by `waba_id`/`phone_number_id`.

**Tech-Provider prerequisites:** **Business Verification + App Review** for advanced access to `whatsapp_business_messaging` + `whatsapp_business_management` (+ `business_management`). **Plan weeks, not minutes, for first approval.**

**vs Solution Partner/BSP:** takes a Meta credit-line, is billed for all tenants, re-invoices with 5–20% markup, becomes merchant-of-record (credit + collections + lock-in). The old On-Behalf-Of single-WABA-for-all-clients model is **deprecated** — Meta now expects per-tenant WABAs. Avoid unless we want to monetize a per-message margin. **Luna (product) is strongly Tech-Provider:** reselling templates is low-quality commodity revenue (we inherit Meta-pricing complaints, billing/support burden, template-category disputes, margin pressure) — *"I would not want AgentProvision to become a WhatsApp toll booth."* We sell the assistant/workflows/outcomes; the tenant owns the number, card, and Meta relationship.

**Pricing & onboarding framing (Luna).** ~$248/mo is sellable **only if framed as operating cost tied to revenue protection** (appointment recovery, fewer missed appts, automated follow-ups, churn reduction, receptionist-labor offset) — **never** as "Meta may charge you $248/mo in messaging fees." If the value is just "AI sends nicer texts," it's a dealbreaker. Onboarding should present **three automation tiers** + a **hard monthly spend cap with pre-cap warnings** (SMBs tolerate usage pricing far better when they feel in control):
- **Low** — critical reminders + task-complete pings only.
- **Recommended** — reminders, delivery pings, follow-ups, high-value reactivation.
- **Aggressive growth** — more marketing/CRM templates, with explicit spend controls.

**Shortcut option:** Phase-1 onboarding *may* ride a flat-fee pass-through partner (**360dialog ~€49-99/number, no Meta markup**) or an onboarding-only layer (Dualhook/Chakra — they sell just the Embedded-Signup + webhook-override + tenant-mapping plumbing; tenants still pay Meta directly), then bring it in-house once volume justifies.

## 5. What changes for Luna (behavior)

Every item is a **hard, non-negotiable** Cloud API constraint vs neonize's send-anything-anytime model:

1. **24h window + templates (the biggest change):** inside the window → unlimited free-form (free). Outside → free-form is **rejected**; Luna can only reach the user via an **approved template** (marketing = paid). She can no longer improvise nightly summaries / "report ready" pings / multi-day follow-ups ad hoc. **Adapt:** branch send logic on per-user window state — (a) open → free-form; (b) closed + suitable template → send template; (c) closed + no template → **cannot send; queue/defer** until the user messages first. Pre-register ~2-3 templates (learning_update / reminder / alert) with correct category + positional `{{1}}/{{2}}` params; keep "utility" strictly transactional or Meta auto-reclassifies to (paid) marketing.
2. **No typing indicator:** Cloud API has no `send_chat_presence(COMPOSING)`. **Adapt:** delete `_keep_typing` (~1849) + the PAUSED tail. Luna's p50 ~5s makes the loss tolerable; optionally send a quick in-window "Working on it…" ack for long queries.
3. **Opt-in (net-new):** explicit opt-in is **mandatory before any first business-initiated contact**; pre-checked boxes / prior SMS consent don't count; easy opt-out required. **Adapt:** gate proactive first-contact on a recorded opt-in.
4. **Quality rating + tier ladder:** Meta scores the number (GREEN/YELLOW/RED). Too many unwanted proactive sends → quality drops → tier freezes/cuts (business-initiated unique-recipient cap per rolling 24h: 250 → 1K → 10K → 100K → unlimited; per-**portfolio** since Oct 2025). **In-window replies are uncapped.** Mar-2026 "preemptive enforcement" can restrict *before* violations are confirmed (rapid list growth, high template velocity without engagement). **Adapt:** Luna must throttle/target proactive sends, never blast; respect ~1 msg/6s per recipient; validate media before send (image ≤5MB, video/audio ≤16MB, doc ≤100MB).

### 5a. Product-contract reframe (Luna's product lens — approve-with-changes)

**Headline (Luna):** this migration **changes the product contract**, and the doc must say so. WhatsApp becomes a **governed customer-operations channel** — a structured notification + conversation-*entry* surface — **not the "unlimited proactive brainstem"** it is on neonize. The *intelligence* lives inside the 24h session, the app, or email. *"Less magical, but more commercially durable."* The move does **not** gut the product, but it kills the implicit promise that Luna can always reach out with rich ad-hoc prose over WhatsApp.

- **Split "proactive" into two modes** (drives every template/defer decision):
  - **Operational proactive** — reminders, delivery pings, follow-ups, payment prompts, "task complete" nudges → naturally **template-shaped**. Migrate as templates.
  - **Cognitive proactive** — rich summaries, reasoning, nuanced results → keep **inside the 24h window**, or in app/email, or **after the user replies**. Never force these out-of-window as templates.
- **Highest product risk = agent-task result pushes** (`agent_tasks.py:84`, §9.0). A genuinely useful result reduced to a canned template *feels broken*. **Required UX:** template states task-complete + an explicit unlock — e.g. *"Your requested task is complete. Reply 'details' to view the result."* — and the reply opens a fresh 24h window that delivers the rich answer immediately. **Don't** send low-value templates just to "stay proactive."
- **Per-behavior adaptation** (Luna, refining §9.0): delivery pings → template (natural). **Nightly "morning report" → do NOT send the full report out-of-window; send a template teaser or move it to email/app.** CRM follow-ups → template, tightly governed by campaign settings + cost caps. Agent-task → template + reply-for-details (above).
- **Template-or-defer UX guardrails:** every deferred item must be visible in the **web/app inbox** (so nothing silently disappears); the template states its category + the required action; the reply unlocks the rich answer; tenants configure **which events justify a paid template**.

## 6. Migration phases (the WAHA abstraction is built in P0, not inherited)

**P0 — build the backend abstraction + single pilot number, direct Cloud API, behind a flag (~1.5–2 sprints — re-baselined; see below).** This phase **constructs** the WAHA-specified-but-never-shipped foundation, not "confirms" it: write `whatsapp_backends/base.py` (`AbstractWhatsAppBackend`), **extract** a `NeonizeBackend` by wrapping the current ~2,684-line `whatsapp_service.py` (zero behavior change — this refactor is the bulk of P0's cost), write `select_backend`, and add migration **158+** for `channel_accounts.backend` (default `'neonize'`) + the identifier metadata (per §3, tokens live in the vault, not a new column). Then build `CloudAPIBackend` (httpx sender + cloud-webhook receiver modeled on `twilio_webhook.py`) for **one pilot number we control** (own Meta App + System User token, **manual provisioning — no Embedded Signup yet**). `select_backend` returns `'cloud-api'` only for the pilot, gated by a `tenant_features` flag. Split `_handle_inbound`; guard the I3 startup/shutdown hooks. Pre-register 2-3 templates. Validate full send/receive + template path. **Why the re-baseline:** the original "~1 sprint" silently assumed the WAHA P1+P2 scaffolding already existed; it doesn't, so the NeonizeBackend extraction + interface + migration are all in scope here.

**P1 — dual-run with neonize (~1 sprint).** Pilot on Cloud API while all other tenants stay on neonize (**different numbers — a number can't be on both Cloud API and the consumer app at once, so dual-run is per-number**). Compare reliability (no QR/disconnect firefights), latency, cost, quality-rating. Keep `session_blob` for neonize rollback. Replace session/heartbeat/reconnect **only on the Cloud API path**. Expand to 2-3 friendly tenants.

**P2 — multi-tenant Embedded Signup / Tech Provider (~1-2 sprints + Meta approval lead time).** Build Embedded Signup + server-side code→token exchange + auto WABA-subscribe + number register + per-tenant webhook override. Complete Business Verification + App Review. New pairing defaults `backend='cloud-api'`; dashboard tile shows cloud-api vs neonize counts. Optionally ride 360dialog/onboarding-only partner to shortcut App Review.

**P3 — retire neonize.** When active-on-neonize count is zero/stale, drop `NeonizeBackend`, the `backend` column, `session_blob`, and decommission the firefighting band-aids (#765 backups, drain, silent-disconnect handlers). **Decision per phase:** keep neonize as a **free-tier fallback** backend, or retire fully? (see §8.)

**Reuse-vs-replace summary:**
- **Reuse verbatim:** fire-and-forget pipeline, chat_jobs state machine, `ChannelAccount` + tenant scoping, `channels.py` endpoints, Fernet vault, internal-token route.
- **Replace:** session persistence, heartbeat/reconnect, QR pairing, typing indicator, the send transport.

## 7. Trade-offs (honest)

| | Official Cloud API | neonize (current) |
|---|---|---|
| Reliability | Meta-hosted; no socket/session to corrupt → **kills the firefight class** | chronic disconnect/QR/corruption firefights |
| Legitimacy | sanctioned; **no ban risk** | pairs a consumer acct vs ToS → **latent ban risk** |
| Scale / multi-tenant | webhooks + Embedded Signup, designed-for | doesn't scale cleanly; per-number QR |
| Proactive messaging | **24h window + templates only** (paid marketing) | free-form anytime, free |
| Cost | per-message templates (~$248/mo example tenant) | free |
| Onboarding | Business Verification + App Review (weeks) + Embedded Signup | QR scan |
| UX niceties | no typing presence; quality-rating governance; opt-in | typing works; no governance |

**Net:** reliability + sanctioned-path + scale strongly favor Cloud API; the price is cost + the proactive constraint + onboarding effort. A **hybrid** (Cloud API for paying/scale tenants, neonize as free-tier fallback) is viable short-term but **doubles maintenance**.

## 8. Open questions (decisions for Simon)

1. **Direct vs BSP for Phase-1 onboarding** — build Embedded Signup + App Review in-house from the start, or ride a flat-fee pass-through (360dialog) / onboarding-only layer (Dualhook/Chakra) to go live faster? *(Lean: P0 pilots direct on one owned number — no Embedded Signup needed yet — then decide for P2.)*
2. **Who pays Meta** — confirm the Tech-Provider model (each tenant's own card, Meta bills them) vs Solution Partner (we front Meta's bill + resell with markup). A business-model call.
3. **Keep neonize as a free-tier fallback,** or retire fully at P3? (keeping = permanent dual-maintenance of the firefight stack.)
4. **Which tenants pilot** P0/P1 — a low-stakes internal number is safest for P0; vet/BB-Cardiology + Chile/Aremko are demo-facing candidates for P1.
5. **Number strategy** — the pilot number is a **one-way door**: it must be deleted from the consumer WhatsApp app first and becomes API-exclusive (neonize can't share it). Fresh number vs migrate an existing Luna number?
6. **Template set** — which proactive scenarios become templates, their categories (utility vs marketing = cost), and the per-tenant approval workflow.

## 9. Risks

### 9.0 Proactive-send inventory — the paths the 24h gate silently breaks (do this before cutover)

Every business-initiated, out-of-window send below currently calls `whatsapp_service.send_message(...)` with **raw free-form text**. Under Cloud API each is **rejected** outside the 24h window and must become an approved template **or** a deferred send. This is the concrete form of "users perceive Luna as gone quiet" — it is the single highest-value artifact in this plan.

| Path | Current behavior | Window state | Cloud-API mapping |
|---|---|---|---|
| `workflows/activities/remedia.py:127` | RemediaOrderWorkflow "📦 Entregado" / delivery updates | almost always **out** (delivery lands hours/days later) | **utility** template (`order_update`) — transactional, keep category strict |
| `workflows/activities/autonomous_learning.py:571` | nightly self-improvement "morning report" condensed to WhatsApp | **out** by definition (overnight) | **utility/marketing** template or **defer** to next user inbound |
| `workflows/activities/follow_up.py:44` | `send_whatsapp` CRM follow-up to an entity's phone, typically days later | **out** | **marketing** template (re-engagement) + opt-in gate, or defer |
| `api/v1/agent_tasks.py:84` | agent-task result push | **in** if the task was user-triggered seconds ago, else **out** | in-window → free-form; out → template or defer |

**Not a break (stated so the council doesn't chase it):** `workflows/activities/proactive_activities.py:send_proactive_notifications` writes `Notification` rows (in-app bell), **not** WhatsApp.

**Cutover gate:** until each row above has a registered template (correct category) or an explicit defer-until-inbound policy, the cloud-api backend must not be enabled for a tenant that depends on these flows.

### 9.1 Risk register

- **Product:** the 24h/template gate may **silently break existing proactive Luna behaviors** — see the §9.0 inventory; do not cut over until each path is mapped, or users perceive Luna as "gone quiet." Template approval latency/rejection (wrong category auto-reject; utility→marketing auto-reclass) can block launch — author conservatively, pre-submit early. Quality downgrade + preemptive enforcement can restrict the number if cadence is too high — throttle/opt-in before multi-tenant send.
- **Engineering:** HMAC over the **raw body** (footgun); media URL ~15-min expiry → synchronous download (preserve ~line 1228); token expiry/rotation/revocation replaces session durability (get refresh solid or inbound silently dies); webhook idempotency by `wamid` (Meta retries 7 days).
- **Cost/business:** per-message cost is new + tenant-billed → surprise bills if proactive volume is mis-modeled (surface estimated cost in onboarding); App Review / Business Verification can take weeks and be rejected (gates P2); **all figures are date-sensitive and partly single-sourced** — committing them to billing without re-confirming Meta's live rate card is a financial risk the council must close.

## 10. Council review checklist (date/version-sensitive — re-confirm against live Meta docs)

(a) Graph API version (cited v23.0; bumps ~quarterly). (b) **All per-message rates, esp. Chile** ($0.0889/$0.02/$0.02 — single-source; CLP billing since Apr 1 2026) — pull the live CSV. (c) Free-tier state (service convos free+unlimited since Nov 1 2024; **no** monthly free template tier — some stale guides cite a 1,000 cap). (d) Tier ladder + Oct-2025 per-portfolio shift. (e) Throughput (80→1000 MPS) + per-pair 6s spacing (BSP-sourced). (f) Mar-2026 preemptive enforcement + Apr-2026 BSUID-in-webhooks. (g) Exact `request_code`/`verify_code`/`register` + interactive/media payload shapes (verify against live reference). (h) Embedded Signup `sessionInfoVersion` v3 vs v4. (i) Per-BM number/WABA limits (raisable). (j) Whether On-Behalf-Of WABA co-ownership is fully deprecated.
