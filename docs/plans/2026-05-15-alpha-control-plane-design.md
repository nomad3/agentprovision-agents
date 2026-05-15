# Alpha Control Plane — Design

**Date:** 2026-05-15
**Status:** Design ready for review (revision 2 — addresses spec-review findings)
**Author:** Brainstorm session, agentprovision platform
**Audience:** Design + engineering before any implementation
**Related:** Continues Luna OS Spatial HUD ([luna_os_spatial_hud.md] memory), supersedes ad-hoc `ChatPage.js`

> **Orientation note.** "Alpha" is the unified product identity (CLI binary + supervisor agent + Tauri app + supervisor name), succeeding "Luna" as of 2026-05-14 ([alpha_brand_identity.md]). Older docs reference Luna; treat them as Alpha unless explicitly about the Tauri client.

## Revision log

- **rev 2b (2026-05-15)** — round-2 review NITs:
  - NIT-1 (`seq_no` allocation): picked `pg_advisory_xact_lock(hashtext(session_id))` + COALESCE(MAX+1) with UNIQUE safety net. Explicit failure-ordering paragraph added.
  - NIT-2 (`auto_quality_score` capability key): added `showAutoQualityScore: true` at tier 4 in `TIER_FEATURES`.
  - Cross-ref: §5.2 WhatsApp binding now explicitly names `chat_sessions(id)` lookup pattern.
- **rev 2 (2026-05-15)** — addresses round-1 spec review:
  - B1 (event protocol vs existing infra): added §5.1 with persistence table schema, v2 endpoint, name-mapping policy.
  - B2 (session identity): added §5.2 defining `session_id` as the unifier and how each channel binds.
  - B3 (tier storage): resolved to `user_preferences.preference_type='alpha_cockpit_tier'` — zero migration needed.
  - I1 (tier gating): added capability-map + `<TierGate>` two-pattern hybrid in §4.
  - I2 (channel × event matrix): added 9×4 rendering matrix.
  - I3 (concurrency): added §5.3 dedupe + no-HTTP-echo model.
  - I4 (pagination): added `limit` + `next_cursor` + compaction policy.
  - I5 (tier switch mid-session): "subsequent renders" + pinned items survive.
  - I6 (resilience): added §5.4 reconnect / replay window / storm policy.
  - I7 (back-compat): v1 endpoint keeps legacy envelope, v2 has new envelope.
  - N1 / N2 / N4 / N5: orientation note + pinnable cap + idle-empty-chunk policy + parked questions expanded + multi-tenant operators resolved.
- **rev 1 (2026-05-15)** — initial draft from brainstorming session.

---

## 1. Why this exists

agentprovision's chat UI today is a single 877-line `ChatPage.js` plus a separate `AgentsPage`, `CoalitionReplayPage`, `IntegrationsPage`, dashboard, fleet health, etc. Each shipped capability (A2A coalition, ALM, skills marketplace v2, memory-first redesign, RL auto-scoring, knowledge graph backfill) lives on its own page, and the user has to know they exist to navigate to them.

The intent of this redesign:

1. **Aggregate every agentic-AI tool the user needs into one workspace.** Memory, projects, leads, datasets, experiments, entities, fleet, skills, deployments — all reachable without page-hopping.
2. **Make agentic AI approachable**: a user who has never touched AI should be able to use the platform and gradually unlock its full power.
3. **Reach god-tier without leaving the workspace**: the same UI grows from "first chat" to "operating a coalition of N CLIs against a multi-tenant fleet."
4. **One brain, many viewports**: alpha CLI in a terminal, Tauri desktop app, web app, WhatsApp — all see the same orchestrator state, rendered for the channel.

The framing: the cockpit is **Luna OS becoming a production operating system**, with **Alpha CLI as the kernel**, the **A2A coalition as the mesh layer**, and the **UI surfaces as channel-agnostic viewports**.

---

## 2. Architecture — three layers

```
┌──────────────────────────────────────────────────┐
│  CHANNELS  (viewports onto the orchestrator)     │
│  alpha CLI │ Web │ Tauri │ WhatsApp │ future…     │
└──────────────────────────────────────────────────┘
                      ↕  channel-agnostic event protocol
┌──────────────────────────────────────────────────┐
│  MESH  (agent-to-agent collaboration)            │
│  A2A coalition │ blackboard │ handoffs            │
│  Inbound-only: leaf → orchestrator via SSE        │
└──────────────────────────────────────────────────┘
                      ↕
┌──────────────────────────────────────────────────┐
│  KERNEL  (alpha CLI as engine, cloud-resident)   │
│  CLI fleet routing │ vault │ memory │ MCP tools   │
│  Workflows │ skills │ RL store                    │
└──────────────────────────────────────────────────┘
```

### Kernel (Alpha CLI as engine)

The CLI is the engine that powers every viewport. Whether the user types in their terminal, the web, the Tauri app, or WhatsApp, the request lands at the same orchestrator code path.

**Deployment topology note (resolves N1):** in local-dev (the current world), the kernel runs as the api / orchestration-worker / code-worker containers in docker-compose on the user's mac. In production, the same containers run in the cloud. "Kernel" refers to the logical layer, not a Kubernetes-specific assumption.

Existing implementations:

- CLI fleet routing (`cli_session_manager.py`) — picks claude_code / codex / gemini_cli / copilot_cli per request, with subscription-OAuth vault credentials (PRs #470/#471) and refresh-token preservation (PR #474).
- Memory (existing memory-core + recall pipeline).
- MCP tools (existing mcp-server).
- Workflows + skills marketplace (shipped).
- RL store (shipped via auto-quality scorer + RL experiences).

The cockpit does **not** introduce new kernel features. It exposes the existing kernel through richer surfaces.

### Mesh (Agent-to-agent collaboration)

A2A coalition is shipped (CoalitionWorkflow, blackboard substrate, Redis SSE, 3 patterns). Today the cockpit will only render the existing mesh — no new mesh primitives required.

**Outbound mesh (cloud → leaf push) is explicitly out of scope for this design.** Corporate firewalls, complexity, and the fact that the inbound channel + cloud-resident CLI fleet already cover the use cases. If/when a future spec wants Luna to dispatch tasks to remote alpha CLIs (Claude-Code-remote-desktop-style), it gets its own design doc.

### Channels (viewports)

Each viewport subscribes to a channel-agnostic event stream (SSE / websocket) and renders the same orchestrator state differently:

| Channel | Renders rich? | Tool calls shown? | Drawer? | Audience |
|---|---|---|---|---|
| **alpha CLI** (terminal) | ANSI text | One-line "→ tool: gmail.send" | inline stream | power users / agents-as-clients |
| **Web cockpit** | Full HTML, all zones | Card components in right panel | yes, multi-tab | anyone tier 0–5 |
| **Tauri app** | Same as web + native menu/notifications | same as web | yes | desktop power users |
| **WhatsApp** | Plain text only | skipped | n/a | casual users on the go |

Same brain, different rendering. Power-user dialect (CLI) and casual dialect (WhatsApp) come for free because both consume the same event stream — they just filter and format differently.

---

## 3. Shell — the cockpit layout

```
┌─[ Left rail ]─┬─────────[ Center ]──────────┬─[ Right panel ]─┐
│  Resource     │   Alpha conversation        │  Context object │
│  navigator    │   + inline plan stepper     │  (file diff,    │
│  (collapsed   │   + inline tool-call cards  │   memory entry, │
│  icon strip,  │                             │   lead card,    │
│  expands on   │                             │   agent feed,   │
│  click)       │                             │   replay, etc.) │
├───────────────┴─────────────────────────────┴─────────────────┤
│  [ Live terminal drawer — collapsible to one-line ticker ]    │
│  Streams cloud worker CLI subprocess output (multi-tab)        │
└───────────────────────────────────────────────────────────────┘
```

### Anchor: conversation-first with direct-manipulation affordances

The alpha conversation is the primary surface. Other panels respond to it (when alpha edits a file, the diff opens in the right panel; when alpha queries memory, matched entries surface there). But every panel is also directly clickable — power users navigate without typing if they prefer.

### Zone-by-zone

#### Center: the conversation
- Alpha thread, message bubbles, inline plan stepper (no separate page).
- Tool calls render as inline cards ("alpha ran `read_library_skill`, result attached").
- Sub-agent dispatches render as collapsible "alpha → coalition → claude_code, codex" cards.
- Input bar at bottom; supports slash commands, file attach, voice (Tauri only initially).

#### Left rail: resource navigator
- Default: icon strip (32px wide). Icons: Memory, Projects, Leads, Datasets, Experiments, Entities, Skills, Fleet.
- Click an icon → expands to mini-list (300px wide overlay). Click an entry → opens in right panel + collapses back to strip.
- Search across resources: `Cmd+K` anywhere → palette over the whole UI.
- Tier-gated: only icons relevant to the current tier appear (see §4).

#### Right panel: context object viewer
- Renders whatever was last referenced — by alpha (tool call, memory hit, agent dispatch) or by user (clicked entry from rail, opened lead, etc.).
- Polymorphic component library: file diff, memory entry, lead card, dataset row, experiment result, agent activity feed, coalition replay, RL experience.
- Pinnable: stack of pinned items in a header strip, click to switch. Default cap 5 items, user-configurable via settings up to 12 (resolves N2). Eviction policy = least-recently-clicked when cap is exceeded.
- Closeable: collapses the right panel to a thin "no context active" bar, giving the conversation more room.

#### Bottom drawer: live terminal
- Streams cloud worker CLI subprocess output (claude / codex / gemini stdout/stderr).
- Multi-tab when multiple subprocess streams active.
- Collapses to a one-line ticker (shows last line of the active tab); click to expand.
- Auto-shown when subprocess starts; auto-collapsed when idle for 30s (unless user has pinned it open). "Idle" means no `cli_subprocess_stream` event with a non-empty `chunk` for 30s; empty-chunk heartbeats do NOT reset the idle timer (resolves N4).

### What's persistent vs summoned

**Persistent** (always present, density varies by tier):
- Center conversation
- Left rail (icon strip)
- Right panel (or its collapsed bar)
- Drawer (or its collapsed ticker)

**Summoned via `Cmd+K` or chat:**
- Cost & usage breakdowns
- Workflow templates picker
- Coalition full-replay (the live mini version lives in the right panel; the full timeline opens as an overlay)
- Deployment / fleet health detail (overlay)
- Settings / integrations / branding

**Triggered automatically by alpha:**
- Sub-agent dispatch → agent's stream renders in the right panel
- File edit → diff opens in the right panel
- Memory query → matched entries surface in the right panel
- User can pin / unpin to keep something visible across alpha's subsequent actions

---

## 4. Maturity tiers — same shell, tier-aware density

The shell skeleton is the same at every tier. **Each zone's content is gated by the user's current tier** (`profile.tier: 0|1|2|3|4|5`). Tier is stored on the user profile; it does not change automatically.

| Tier | Persona | Visible affordances |
|---|---|---|
| **0 — First touch** | Brand new, no integrations, 0 chats | Conversation only. Rail = single "+" connect button. Right panel = welcome card. Drawer hidden. |
| **1 — Connected** | ≥1 integration connected | Rail populates with connected integrations + Memory icon. Tool calls render inline as cards in the chat. |
| **2 — Multi-agent** | Ran first coalition | Plan stepper appears inline in chat. Right panel can show active agents during coalition runs. Recent activity strip becomes visible. |
| **3 — Workspace** | Manages projects / leads / datasets | Full resource browsers in rail (all 8 icons). Right panel pins context. Power-user palette (`Cmd+K`) unlocked. |
| **4 — Operator** | Manages fleet / experiments / RL | Fleet, deployments, RL experiences in rail. Drawer on by default, multi-tab visible. Auto-quality scoring surfaces are visible. |
| **5 — God** | Customising the platform | Workflow editor, skill authoring, RL query, alpha policy editor. Full chrome. Settings exposes feature flags + advanced toggles. |

### Tier progression — explicit picker (P3)

User chooses their tier in onboarding **and** in settings. Picker is one screen with a labelled example per tier ("Tier 2 looks like X, click to preview"). User can change anytime; promotion and demotion are equally valid.

**Why explicit instead of auto-detect:** auto-progression risks the UI shifting under the user without warning. A senior dev doesn't want to "earn" tier 4 by triggering a magic threshold — they want to flip a switch. A new user doesn't want to feel demoted if they take a week off. Explicit ownership respects both.

Telemetry can suggest tier promotion in a one-time non-blocking nudge (`"You've connected 3 integrations and run a coalition — sounds like Tier 2 fits. Switch?"`), but the act of changing tier is always the user's explicit choice. No silent transitions.

### Tier 0 starter state — hybrid

Default empty (welcoming). A discreet "Show me what this can become" toggle in the corner grays-in the rest of the cockpit so the user can preview the destination without it being in their face. The toggle is sticky — once they've used it, the cockpit knows they've seen it and stops surfacing it.

This is the recommendation. The toggle text + placement should be designed to feel like an invitation, not a tutorial pop-up.

### Tier storage (resolves B3)

Tier lives in the existing `user_preferences` table — no migration needed.

- `preference_type = 'alpha_cockpit_tier'`
- `value = '0' | '1' | '2' | '3' | '4' | '5'`  (string, parsed to int at read time)
- One row per `(tenant_id, user_id)`. Default tier 0 created on signup.

A thin helper service (`apps/api/app/services/user_tier.py`) provides `get_tier(user_id, tenant_id) -> int` and `set_tier(user_id, tenant_id, tier: int)`. Picker UI hits a `PUT /api/v1/users/me/cockpit-tier` endpoint that wraps `set_tier`. The cockpit-tier value rides in the JWT after refresh so the SPA doesn't have to fetch it on every render — but the source of truth is `user_preferences`.

### Tier gating mechanism (resolves I1)

Two-pattern hybrid; both required:

1. **Capability map + `useTier()` hook** (for fine-grained UI gating inside components):
   ```js
   // apps/web/src/cockpit/tierFeatures.js
   export const TIER_FEATURES = {
     0: { showRail: false, showRightPanel: false, showDrawer: false, allowedRailIcons: [] },
     1: { showRail: true, showRightPanel: 'limited', showDrawer: false,
          allowedRailIcons: ['integrations', 'memory'] },
     2: { showRail: true, showRightPanel: true, showPlanStepper: true,
          allowedRailIcons: ['integrations', 'memory', 'projects'] },
     3: { showRail: true, showRightPanel: true, showPalette: true,
          allowedRailIcons: ['integrations', 'memory', 'projects', 'leads',
                             'datasets', 'experiments', 'entities', 'skills'] },
     4: { ...tier3, showDrawerByDefault: true, showAutoQualityScore: true,
          allowedRailIcons: [...tier3.allowedRailIcons, 'fleet', 'deployments', 'rl'] },
     5: { ...tier4, showWorkflowEditor: true, showSkillAuthor: true,
          showPolicyEditor: true, /* all icons */ },
   };
   ```
2. **`<TierGate min={N}>` component wrapper** (for whole-component gating):
   ```jsx
   <TierGate min={2}>
     <PlanStepper session={session} />
   </TierGate>
   ```
   Renders nothing if user's tier < `min`. Has a `fallback` prop for tier-aware skeletons.

This keeps the maze out: fine-grained switches live in one map; whole-component gates wrap at their declaration site, not inline. No `if (tier >= 3)` scattered through component bodies.

### Tier-switch behaviour mid-session (resolves I5)

Tier changes apply to **subsequent renders**, not in-flight UI. Concretely:

- The `useTier()` hook re-emits on the new tier; React re-renders all subscribers naturally.
- Components that are already mounted (e.g., a `<PlanStepper>` pinned in the right panel) unmount/remount based on their `<TierGate>`.
- The user's currently-pinned right-panel context survives even if their new tier wouldn't show it by default — pinned items are sticky until explicitly closed. (Demotion is non-destructive.)
- Toast on tier change: "Tier set to N — some panels will adjust." Single notification, no modal.

---

## 5. Channel-agnostic event protocol

The orchestrator emits a single event stream that every channel subscribes to. Each event is a JSON envelope:

```json
{
  "event_id": "evt_…",
  "session_id": "ses_…",
  "tenant_id": "…",
  "ts": "2026-05-15T12:14:19Z",
  "type": "tool_call_started" | "tool_call_complete" | …,
  "payload": { … }
}
```

### Event types (minimum viable set)

| Type | Payload | Emitted when |
|---|---|---|
| `chat_message` | `{role: 'user'\|'alpha', text, attachments[]}` | New chat turn |
| `tool_call_started` | `{tool_name, args, mcp_server}` | alpha invokes an MCP tool |
| `tool_call_complete` | `{tool_name, result, error?, latency_ms}` | tool returns |
| `plan_step_changed` | `{step_index, label, status}` | workflow step transitions |
| `subagent_dispatched` | `{agent_id, role, prompt}` | coalition dispatches a peer |
| `subagent_response` | `{agent_id, text}` | peer responds |
| `cli_subprocess_stream` | `{platform, fd, chunk}` | claude/codex/gemini emits stdout/stderr |
| `resource_referenced` | `{resource_type, resource_id, kind: 'read'\|'write'}` | alpha touched memory/lead/dataset/etc. |
| `auto_quality_score` | `{score, consensus, reviews[]}` | scorer rates a response |

### Channel × event-type rendering matrix (resolves I2)

Filtering is **client-side** (every channel subscribes to the full stream and filters; server doesn't fan out per-channel filtered streams — keeps the wire protocol uniform):

| Event type | alpha CLI | Web cockpit | Tauri | WhatsApp |
|---|---|---|---|---|
| `chat_message` | ✅ rendered as text | ✅ message bubble | ✅ same as web | ✅ delivered as WA message |
| `tool_call_started` | ✅ one-line `→ tool: X` | ✅ inline card | ✅ inline card | ❌ dropped |
| `tool_call_complete` | ✅ one-line `✓ tool: X (123ms)` | ✅ updates card | ✅ updates card | ❌ dropped |
| `plan_step_changed` | ✅ `[3/7] step label` | ✅ stepper UI | ✅ stepper UI | 🟡 throttled — only emit transitions to/from terminal states (`started`, `complete`, `failed`); skip intermediate `running` |
| `subagent_dispatched` | ✅ `[fan-out] codex…` | ✅ collapsible card | ✅ collapsible card | ❌ dropped |
| `subagent_response` | ✅ indented text | ✅ collapsible card | ✅ collapsible card | 🟡 inline if response is the final answer to user; else dropped |
| `cli_subprocess_stream` | ❌ dropped (CLI is the subprocess on the other side; loop would be confusing) | ✅ drawer | ✅ drawer | ❌ dropped |
| `resource_referenced` | ✅ `[mem] read entity-123` | ✅ surfaces in right panel | ✅ same as web | ❌ dropped |
| `auto_quality_score` | 🟡 only if tier ≥4 | 🟡 tier ≥4 | 🟡 tier ≥4 | ❌ dropped |

Symbols: ✅ rendered • ❌ dropped • 🟡 conditional / coalesced.

The filter table is implemented as a const in each channel adapter (`apps/api/app/channels/{cli,web,whatsapp,tauri}_filter.py` or the equivalent client-side filter in JS), not as a server policy. This avoids server-side per-channel branching and lets each channel team own their rendering trade-offs.

### Ordering + replay semantics

- Strict per-session ordering (events arrive in the order they happened).
- Each event has a monotonic `seq_no` per session for client-side resync.
- Replay: a viewport can `GET /api/v2/sessions/{id}/events?since=seq_no&limit=100` to catch up after a disconnect.
- Pagination: response includes `events[]` + `next_cursor` (last `seq_no` returned). Default `limit=100`, max 500. Clients page until `next_cursor` is null.
- Compaction on replay: `cli_subprocess_stream` chunks are coalesced into one event per 5-second window (raw chunks live in original SSE; replay summarises to keep the response bounded).
- Retention: raw events 30 days; `auto_quality_score` indefinite (feeds RL store).

The exact transport (SSE vs websocket) is left to the channel-protocol spec — both work, the event shape is the same.

### 5.1 Relationship to existing `collaboration_events` infrastructure

The codebase already has session SSE infrastructure that this protocol must coexist with:

| Existing | Where | What |
|---|---|---|
| `publish_session_event(session_id, type, payload)` | `apps/api/app/services/collaboration_events.py:53` | Redis pub/sub fan-out, **no persistence, no seq_no, no replay** |
| `publish_event(collaboration_id, type, payload)` | same file:37 | per-coalition fan-out |
| `GET /api/v1/sessions/{id}/events` | `apps/api/app/api/v1/chat.py` | Existing SSE consumer (`ChatPage.js`) |
| Event names today | runtime | `collaboration_started`, `collaboration_completed`, `phase_started`, `blackboard_entry`, `agent_response`, etc. |

**Relationship strategy:**

1. **Additive, not replacing.** The 9 new event types in §5 above are **added alongside** the existing coalition-lifecycle events. Old names keep being emitted; new names are emitted for the new granular surfaces (tool calls, plan steps, subprocess streams, resource refs). One stream, both vocabularies.
2. **Persistence side-channel.** New table `session_events` (Postgres) records every published event with a per-session monotonic `seq_no`. Redis pub/sub stays as the live fan-out; the table is what makes replay possible. Persistence runs in the same `publish_session_event` call (write-then-publish; if Redis fan-out fails the event is still in Postgres for replay).
3. **Endpoint versioning for back-compat (resolves I7).** Existing `/api/v1/sessions/{id}/events` keeps its current envelope `{event_type, payload, timestamp}`. New cockpit uses `/api/v2/sessions/{id}/events` with the full envelope (`event_id`, `seq_no`, `tenant_id`, `ts`, `type`, `payload`). Old `ChatPage.js` is unchanged until migrated.
4. **Name mapping at the v2 boundary.** Legacy event types (`collaboration_started`, etc.) are surfaced on v2 with type prefix `legacy.collaboration_started`; clients (and the cockpit) treat them as advisory and don't break on unknown legacy types. This means v2 is a strict superset of v1's information.

**Schema sketch (`session_events`):**
```sql
CREATE TABLE session_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  tenant_id    UUID NOT NULL,
  seq_no       BIGINT NOT NULL,
  event_type   VARCHAR(64) NOT NULL,
  payload      JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (session_id, seq_no)
);
CREATE INDEX session_events_session_seq ON session_events(session_id, seq_no);
CREATE INDEX session_events_tenant_created ON session_events(tenant_id, created_at);
```

**`seq_no` allocation:** Postgres transaction-scoped advisory lock keyed by session.

```sql
BEGIN;
SELECT pg_advisory_xact_lock(hashtext($session_id::text));
INSERT INTO session_events (session_id, tenant_id, seq_no, event_type, payload)
VALUES ($session_id, $tenant_id,
        COALESCE((SELECT MAX(seq_no) FROM session_events WHERE session_id = $session_id), 0) + 1,
        $type, $payload);
-- only AFTER commit: publish to Redis (write-then-publish per §5.1)
COMMIT;
```

Stateless (no counter row needed), correctly serializes concurrent publishers in the same session (a coalition activity emitting while a user POSTs), and the lock auto-releases at COMMIT/ROLLBACK. Cross-session writes don't contend. The `UNIQUE(session_id, seq_no)` index is the safety net if the advisory lock is ever bypassed.

**Failure ordering**: if the Postgres INSERT fails (constraint violation, connection drop), the Redis publish is **skipped** — caller returns an error. If the INSERT commits but the Redis publish fails (broker down, network), live SSE listeners miss the event but the next reconnect-with-`since=seq_no` recovers it via replay; this is the case §5.4's 250ms warmup window is designed for.

**30-day retention:** daily cron `DELETE WHERE created_at < NOW() - INTERVAL '30 days'`.

### 5.2 Session identity across channels

A **session** is the unit that channels subscribe to. `session_id` is the unifier across CLI, Web, Tauri, WhatsApp.

- **Web / Tauri**: explicit. User creates / picks a session via the existing `/sessions` endpoint. Cockpit opens to the last-active session by default.
- **WhatsApp**: implicit. The existing channel-account → conversation mapping resolves to a `session_id` server-side via a real `chat_sessions` row (`source='whatsapp'`, `external_id=session_key`). One conversation thread = one `chat_sessions.id` = one session_events stream. (No design change here; this is how WhatsApp routing already works in `whatsapp_service.py:964–973`.)
- **Alpha CLI**: new `alpha attach <session_id>` and `alpha session new` commands. Auto-resumes last session when invoked without args. Binds via user-scoped JWT (not agent-scoped — agent-scoped MCP JWTs continue to flow to mcp-server for tool calls, but the human-facing CLI uses a user JWT). Per `cli_as_agent_control_plane.md` the bidirectional model is preserved: user-mode alpha calls the orchestrator with their user JWT; agent-mode (leaf alpha invoking MCP tools) uses the agent-scoped JWT.
- **Multi-channel concurrent**: same `session_id` opened from N channels → N subscribers to the same event stream. Single source of truth.

The "multi-tenant operator" question parked in §8 of v1 is the same shape problem and is resolved here: operators get a tenant switcher (cockpit-level UI), and each tenant view scopes its session list. No aggregation across tenants — that would muddle the session model.

### 5.3 Concurrency model — multi-channel echo + dedupe

When the same user is on Web + Tauri + WhatsApp simultaneously and sends a message from any one:

1. **POST returns ack only** (`{event_id, seq_no, ts}`), not the rendered message.
2. **All channels (including the sender) receive the message via SSE** as a `chat_message` event with the same `event_id`.
3. **Clients dedupe by `event_id`** — if a channel optimistically rendered before SSE delivery (typical UX), it reconciles by `event_id` when the SSE event arrives (idempotent re-render).
4. **No HTTP echo.** This avoids the "POST returns the message, SSE also delivers it, render twice" race.

Coalition replies, WhatsApp messages, and Tauri turns all flow the same way: write once (with allocated `seq_no`), broadcast to subscribers.

### 5.4 Resilience — disconnect, replay, reconnect storm

- **SSE drops mid-stream**: client reconnects with `since=<last_seq_no>`. Server replays from `session_events` table.
- **Replay window cap**: 24h max (smaller than the 30-day retention). If client's `since` is older than 24h, server returns `409` with `latest_seq_no` and a `events_skipped: true` flag. Cockpit surfaces "you've been disconnected for over a day, opened a fresh view from session start" with a one-click "load full history" overlay.
- **Reconnect storm policy**: cockpit waits 250ms after subscription before fetching `since=seq_no` (gives the SSE channel a chance to deliver any in-flight events). Replay request is rate-limited per-session to 1 per 5s.
- **Coalesced streams on replay**: per §5 above, `cli_subprocess_stream` chunks are summarised on replay. Live SSE keeps original chunk granularity.
- **Channel-offline queueing**: WhatsApp delivery already has its own retry queue (existing service). Cockpit views don't queue; they replay on reconnect.

---

## 6. What this redesign explicitly does NOT cover

Each of these becomes its own design doc, slotting into the shell:

1. **Live terminal stream spec** — protocol from cloud worker → channel, multi-stream tab management, ANSI rendering, scrollback retention.
2. **Plan stepper / workflow state machine** — render rules, persistence, intervention semantics ("pause at step 3", "edit plan", "skip step").
3. **Right panel context library** — file diff, memory entry, lead card, dataset row, experiment result, agent activity feed, coalition replay, RL experience inspector. Each gets a component contract.
4. **Tier system implementation** — picker UI, profile field, tier-gated component visibility, the "what this can become" preview.
5. **Resource browser unification** — condensed views for memory / projects / leads / datasets / experiments / entities. How they cohabit the rail without becoming a tab soup.
6. **Channel-agnostic event protocol** — event shapes, ordering guarantees, replay semantics, transport choice, auth model.
7. **Outbound mesh** (out of scope for now, future).

Each of these gets its own brainstorm → spec → plan cycle.

---

## 7. Migration strategy

The existing `ChatPage.js` (877 lines), `AgentsPage`, `CoalitionReplayPage`, `IntegrationsPage` continue to work during the transition. Approach:

1. Build the new cockpit at a new route (`/cockpit` initially).
2. Implement at tier 0–1 only — chat + integrations rail. Pilot internally.
3. Add tiers 2–3 in subsequent specs (one or two tiers per release).
4. When tier 3 is stable, default `/dashboard` to the cockpit and demote the old pages to legacy routes (`/legacy/chat`, etc.).
5. Tier 4–5 land last; until then, power-user features remain on their existing pages.

The cockpit + old pages share the same backend, so no data migration is required.

---

## 8. Open questions parked for now

- **Voice input** in Tauri: hot-key push-to-talk vs always-listening. Defer to Tauri-specific spec.
- **Small-viewport rendering (mobile + tablet)** (resolves N5 first half): does the 3-zone shell collapse to single-zone (just chat, everything else accessed via overflow menu) on phones, and to 2-zone (drop the rail, keep center + right panel as 2-column) on tablets? Probably yes, but the breakpoints + collapse rules deferred to a "responsive cockpit" spec.
- **Multi-tenant operators** — *resolved in §5.2*: tenant switcher in the cockpit shell, each tenant view scopes its session list.
- **Plugin model**: if a tenant wants to add a custom resource type to the rail, how? Defer to a "marketplace v3" spec.
- **Per-tenant tier overrides** (resolves N5 second half): can a tenant admin redefine what tier 2 means for their users (e.g., "tier 2 always shows the drawer")? Likely yes via tenant_features overrides on the `TIER_FEATURES` map, but the override grammar + admin UI deferred to its own spec.
- **Per-user fleet sharding**: a user with 5 separate alpha CLI sessions on different machines — do they all merge into one cockpit timeline or stay separate? Tied to whether we ever ship outbound mesh. Defer.

---

## 9. Next steps

1. **Spec review loop** — dispatch spec-document-reviewer subagent against this doc. Address issues, iterate.
2. **User review** — request human sign-off on this design before any code.
3. **Plan doc** — invoke writing-plans skill against this design to produce an implementation plan for **tier 0–1 first** (smallest shippable cockpit: chat + integrations rail).
4. **Tier 0–1 implementation** — new React route + minimal backend event-stream surface. No new kernel work.
5. **Follow-up brainstorms** for sections in §6 — one per spec, each with its own design doc and review loop.

---

## References

- `apps/web/src/pages/ChatPage.js` (877 lines) — existing chat surface to evolve
- `apps/web/src/pages/AgentsPage.js`, `CoalitionReplayPage.js`, `IntegrationsPage.js`, `DashboardPage.js` — pages to consolidate
- Memory: [luna_os_spatial_hud.md] — prior Luna OS HUD brainstorm
- Memory: [alpha_brand_identity.md] — Alpha as unified product identity (2026-05-14)
- Memory: [cli_as_agent_control_plane.md] + [leaf_agent_inbound_via_mcp.md] — existing inbound channel
- Memory: [a2a_collaboration.md] — shipped A2A coalition
- Memory: [memory_first_design.md] — shipped memory infrastructure
- Memory: [skills_marketplace_v2.md] — shipped skill platform
- Memory: [alm_platform.md] — shipped agent lifecycle management
