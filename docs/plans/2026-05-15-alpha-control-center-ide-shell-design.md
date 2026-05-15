# Alpha Control Center — IDE Shell Design

**Date:** 2026-05-15
**Status:** Phase 1 implementation underway
**Supersedes (UI shape only):** `2026-05-15-alpha-control-plane-design.md` §3 (was a /den-style 3-zone shell with tier picker)
**Keeps from prior design:** §2 architecture (CLI=kernel, A2A=mesh, channels=viewports), §5 channel-agnostic event protocol, §5.1 session_events persistence + dual-write, §5.2 session identity model, §5.3 dedupe, §5.4 resilience

---

## Why this revision

The prior `/den` shell shipped as a parallel route with 6 maturity tiers, a tier picker, and a deliberate "you have to pick a tier" gating UX. In practice it duplicated the existing Dashboard + AI Chat surfaces and added a tier abstraction the user explicitly rejected ("REMOVE THAT DEN THING YOU CREATED THAT WAS NOT EXPECTED — we needed to consolidate and enhance what we have").

This revision:

1. **Drops the tier picker and the Den concept entirely.** All `user_tier`, `den_tier` JWT claim, and `/users/me/den-tier` endpoints are deleted.
2. **Keeps the kernel.** Alpha CLI is still the engine; the SPA is still a thin viewport.
3. **Keeps the channel-agnostic event protocol.** `session_events` table, `/api/v2/sessions/{id}/events`, `publish_session_event` dual-write all stay — they're genuine infrastructure with multiple consumers (AgentActivityPanel, future Live Activity, future Plan Stepper).
4. **Replaces the parallel /den route** with a VSCode/Cursor-style IDE shell mounted at the **existing `/dashboard` route**. The merged surface is conversation-first but lays out like an IDE so the user gets a familiar working environment.

---

## Layout

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ TitleBar:  agentprovision  ·  Session: <title>  ·  user ▾  · [toggle Right]      │
├──┬──────────────────┬───────────────────────────────────┬───────────────────────┤
│AB│  SideBar         │   EditorArea (multi-tab)          │  AgentActivityPanel    │
│  │                  │                                   │  (right pane, live v2)│
│  │  per-icon panel  │   tabs[]: chat | agent | memory   │                       │
│  │  Chat sessions   │           skill | workflow        │   live timeline of    │
│  │  Agents          │                                   │   tool calls,         │
│  │  Memory          │   active tab body fills           │   subagent dispatch,  │
│  │  Skills          │   editor area                     │   resource refs       │
│  │  Workflows       │                                   │                       │
│  │  Integrations    │                                   │                       │
├──┴──────────────────┴───────────────────────────────────┴───────────────────────┤
│ StatusBar:  ● kernel: alpha-cli   tenant: xxxx   session: yyyy        ⌘K · …   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Zones

| Zone | Width | Component | Role |
|---|---|---|---|
| TitleBar | 100% × 38 px | `TitleBar.js` | session title, user menu, toggle right panel |
| ActivityBar | 48 px | `ActivityBar.js` | 6 vertical icons; click swaps the SideBar's panel; click-same toggles collapse |
| SideBar | 280 px (collapsible to 0) | `SideBar.js` + `panels/*.js` | resource explorer; one panel per activity icon |
| EditorArea | remainder | `EditorArea.js` + `tabs/*.js` | multi-tab workspace; tabs survive a refresh via localStorage |
| AgentActivityPanel | 340 px (collapsible) | `AgentActivityPanel.js` | live v2 SSE feed for the active chat session |
| StatusBar | 100% × 24 px | `StatusBar.js` | kernel/tenant/session hints |

### Activity icons (Phase 1)

`chat`, `agents`, `memory`, `skills`, `workflows`, `integrations`. Each maps to a sidebar panel that either lists entities (Chat sessions, Agents) or deep-links into the existing rich pages (Memory, Skills, Workflows, Integrations).

### Tab kinds (Phase 1)

Only `chat` ships as a first-class editor tab. Other content (agents, memory entries, skills, workflows) opens in the existing legacy pages via deep links. Phase 2 will add `agent`, `memory`, `skill`, `workflow` tab kinds so power users can pin them alongside chats.

---

## Architecture — preserved from prior design

Alpha CLI is the kernel. Every chat / tool / memory call from the IDE lands at the FastAPI server (`apps/api`) and is dispatched via `cli_session_manager.py` to one of the CLI workers (claude_code / codex / gemini_cli / copilot_cli). No LLM call is made directly from the browser.

```
┌──────────────────────────────────────────────────┐
│  CHANNELS (this PR ships the Web viewport)       │
│  Web IDE shell │ alpha CLI │ Tauri │ WhatsApp     │
└──────────────────────────────────────────────────┘
                      ↕  channel-agnostic event protocol
                      ↕  /api/v2/sessions/{id}/events (SSE + JSON replay)
┌──────────────────────────────────────────────────┐
│  MESH (existing A2A coalition)                   │
│  CoalitionWorkflow │ blackboard │ handoffs        │
└──────────────────────────────────────────────────┘
                      ↕
┌──────────────────────────────────────────────────┐
│  KERNEL (Alpha CLI, cloud-resident)              │
│  cli_session_manager │ memory │ MCP tools         │
│  workflows │ skills │ RL store                    │
└──────────────────────────────────────────────────┘
```

---

## Event protocol (carried over)

`/api/v2/sessions/{id}/events` keeps the envelope from the prior design doc §5:

```json
{
  "event_id": "evt_…",
  "session_id": "ses_…",
  "tenant_id": "…",
  "ts": "2026-05-15T…",
  "seq_no": 42,
  "type": "tool_call_started" | …,
  "payload": { … }
}
```

AgentActivityPanel subscribes via `useV2SessionEvents(sessionId)`; dedupes by `event_id`; renders 9 event types with type-specific icons. Source of truth is the `session_events` Postgres table (migration 133) with `pg_advisory_xact_lock(hashtext(session_id))` for monotonic seq_no.

---

## What got deleted from prior design

| Deleted | Why |
|---|---|
| `/den` route + `apps/web/src/den/` folder | Parallel cockpit duplicated existing pages |
| `TIER_FEATURES` capability map, `useTier()` hook, `<TierGate>` | Tier abstraction explicitly rejected by user |
| `apps/api/app/services/user_tier.py` | No consumer |
| `GET/PUT /api/v1/users/me/den-tier` | No consumer |
| `den_tier` JWT claim mint in `auth.py` (both login + refresh) | No consumer |
| `user_preferences.alpha_den_tier` rows | Will be left in place (no harm); cleanup migration optional |

---

## What got kept from prior design

| Kept | Reason |
|---|---|
| `session_events` table (migration 133) | Generic per-session event log; useful for many surfaces |
| `/api/v2/sessions/{id}/events` (SSE + JSON replay + coalesce) | Reusable across viewports |
| `publish_session_event` dual-write to v1 + v2 channels | Lets legacy ChatPage keep working untouched |
| `tabs/`, `panels/` directory structure pattern | Maps cleanly onto an IDE shell |

---

## File map (this PR)

**Added (Phase 1):**
- `apps/web/src/dashboard/DashboardShell.js` + `.css`
- `apps/web/src/dashboard/TitleBar.js` + `.css`
- `apps/web/src/dashboard/ActivityBar.js` + `.css`
- `apps/web/src/dashboard/SideBar.js` + `.css`
- `apps/web/src/dashboard/EditorArea.js` + `.css`
- `apps/web/src/dashboard/AgentActivityPanel.js` + `.css`
- `apps/web/src/dashboard/StatusBar.js` + `.css`
- `apps/web/src/dashboard/hooks/useTabs.js`
- `apps/web/src/dashboard/hooks/useV2SessionEvents.js`
- `apps/web/src/dashboard/tabs/ChatTab.js` + `.css`
- `apps/web/src/dashboard/tabs/EmptyTab.js`
- `apps/web/src/dashboard/panels/SessionsPanel.js`
- `apps/web/src/dashboard/panels/AgentsPanel.js`
- `apps/web/src/dashboard/panels/MemoryPanel.js`
- `apps/web/src/dashboard/panels/SkillsPanel.js`
- `apps/web/src/dashboard/panels/WorkflowsPanel.js`
- `apps/web/src/dashboard/panels/IntegrationsPanel.js`

**Modified:**
- `apps/web/src/App.js` — mount DashboardShell at `/dashboard`; keep old widgets at `/dashboard/legacy`
- `apps/api/app/api/v1/users.py` — drop `/users/me/den-tier` endpoints + import
- `apps/api/app/api/v1/auth.py` — drop `den_tier` JWT claim mint (login + refresh)

**Renamed:**
- `apps/web/src/pages/DashboardPage.js` → `DashboardLegacyPage.js` (legacy widget surface)

**Deleted:**
- `apps/api/app/services/user_tier.py`

---

## Phasing

**Phase 1 (this PR):**
- Shell skeleton with 5 zones
- 6 activity-bar icons + sidebar panels (Chat lists sessions; others deep-link)
- Chat tab kind with minimal thread + send box
- AgentActivityPanel live on v2 SSE
- Strip Den scaffolding
- Legacy widget dashboard at `/dashboard/legacy`

**Phase 2:**
- Terminal drawer (bottom; multi-CLI tabs; consumes `cli_subprocess_stream`)
- ⌘K command palette
- Pinned context items (file diff renderer, memory entry preview)
- Plan stepper inline in chat tab
- Workflow editor as a `workflow` tab kind
- Multi-tab management UI (drag-reorder, split view)

**Phase 3:**
- Multi-tenant operator switcher in TitleBar
- ⌘P quick session picker (Cursor-style)
- Popout: tab → standalone window (Tauri parity)
- `agent`, `memory`, `skill` tab kinds for in-shell editing
- Delete `/dashboard/legacy` route

---

## Test plan (Phase 1)

- [ ] `/dashboard` renders the IDE shell
- [ ] `/dashboard/legacy` renders the old widget dashboard
- [ ] Activity-bar icon click swaps the SideBar panel
- [ ] Clicking the same activity icon twice collapses the SideBar
- [ ] Right-panel toggle in TitleBar collapses/restores the AgentActivityPanel
- [ ] Sessions in SessionsPanel open as a chat tab in EditorArea
- [ ] Chat tab loads messages for the selected session
- [ ] Sending a message streams the assistant reply
- [ ] AgentActivityPanel shows "● live" once SSE connects
- [ ] AgentActivityPanel renders events as they stream
- [ ] Tabs survive a page refresh (localStorage)
- [ ] Closing the last tab leaves an empty state with a link to `/chat`
- [ ] StatusBar shows tenant + session + `kernel: alpha-cli`
- [ ] No `den_tier` claim in newly minted JWTs (login + refresh)
- [ ] `/users/me/den-tier` returns 404 (route removed)
- [ ] Existing pages (`/chat`, `/agents`, `/insights/*`, `/memory`, `/learning`, `/skills`, `/workflows`, `/integrations`, `/settings`) still load and function

---

## Open questions / parked

- **MCP tool `read_session_events`** (agents query their own audit log): scoped out of Phase 1 to keep PR size focused; lands in Phase 2 with the rest of the terminal-drawer wiring.
- **Mobile/tablet collapse** for the IDE shell: probably collapse to single-zone on phones, two-zone on tablets. Defer to a responsive-shell spec.
- **Theme**: shell defaults to dark surface (`--ap-shell-bg`); needs a light-mode pass. Defer.
- **i18n**: shell strings are English-only in P1; subnav config patterns will apply when we add localized labels.
