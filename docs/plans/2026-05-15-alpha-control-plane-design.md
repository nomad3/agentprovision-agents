# Alpha Control Plane — Design

**Date:** 2026-05-15
**Status:** Design ready for review
**Author:** Brainstorm session, agentprovision platform
**Audience:** Design + engineering before any implementation
**Related:** Continues Luna OS Spatial HUD ([luna_os_spatial_hud.md] memory), supersedes ad-hoc `ChatPage.js`

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

The CLI is the engine that powers every viewport. Whether the user types in their terminal, the web, the Tauri app, or WhatsApp, the request lands at the same orchestrator code path. Existing implementations:

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
- Pinnable: stack of pinned items in a header strip, click to switch.
- Closeable: collapses the right panel to a thin "no context active" bar, giving the conversation more room.

#### Bottom drawer: live terminal
- Streams cloud worker CLI subprocess output (claude / codex / gemini stdout/stderr).
- Multi-tab when multiple subprocess streams active.
- Collapses to a one-line ticker (shows last line of the active tab); click to expand.
- Auto-shown when subprocess starts; auto-collapsed when idle for 30s (unless user has pinned it open).

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

### Ordering + replay semantics

- Strict per-session ordering (events arrive in the order they happened).
- Each event has a monotonic `seq_no` per session for client-side resync.
- Replay: a viewport can `GET /sessions/{id}/events?since=seq_no` to catch up after a disconnect.
- Retention: 30 days raw events, indefinite for `auto_quality_score` (feeds the RL store).

The exact transport (SSE vs websocket) is left to the channel-protocol spec — both work, the event shape is the same.

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
- **Mobile web** (small viewport): does the 3-zone shell collapse to single-zone (just chat, everything else accessed via overflow menu)? Probably yes, but detailed spec deferred.
- **Multi-tenant operators**: a user who admins many tenants — does the cockpit show one tenant at a time with a switcher, or aggregate? Lean toward switcher, but defer.
- **Plugin model**: if a tenant wants to add a custom resource type to the rail, how? Defer to a "marketplace v3" spec.

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
