# Alpha Control Center — Dashboard Architecture

**Route:** `/dashboard` (`apps/web/src/pages/DashboardControlCenter.js`)
**Status:** Shipped (PRs #495–#517, 2026-05-15 → 2026-05-16)
**Supersedes (UI shape only):** `docs/plans/2026-05-15-alpha-control-plane-design.md` §3
**Authoritative design:** [`../plans/2026-05-15-alpha-control-center-ide-shell-design.md`](../plans/2026-05-15-alpha-control-center-ide-shell-design.md)
**Pane composition spec:** [`../plans/2026-05-16-dashboard-split-pane-spec-doc-viewer.md`](../plans/2026-05-16-dashboard-split-pane-spec-doc-viewer.md)
**Terminal redesign / full CLI output:** [`../plans/2026-05-16-terminal-full-cli-output.md`](../plans/2026-05-16-terminal-full-cli-output.md)

The old `/chat` ChatPage and `/dashboard` overview are merged into a single VSCode/Cursor-style IDE shell at `/dashboard`. Conversation-first, but laid out like an editor so power users can keep chats, file viewers, and live agent activity in view simultaneously.

---

## 1. Layout

```
┌────────────────────────────────────────────────────────────────────────┐
│ TitleBar · session title · ⚡ A2A · ⌘K · Pro/Simple toggle · user ▾    │
├────────────┬───────────────────────────────────────┬───────────────────┤
│ Left card  │  EditorArea (1..4 chat groups)        │ AgentActivityPanel│
│            │  ──────────────────────────────────── │ (right; Pro only) │
│ Chats │    │  active session per group;            │                   │
│ Files      │  vertical splits between groups       │ live v2 SSE feed: │
│            │  (ResizableSplit, persisted sizes)    │ tool calls,       │
│ session    │                                       │ subagent dispatch,│
│ list OR    │                                       │ plan steps,       │
│ tenant /   │                                       │ resource refs,    │
│ platform   │                                       │ quality consensus │
│ file tree  │                                       │                   │
├────────────┴───────────────────────────────────────┴───────────────────┤
│  Horizontal resize handle                                              │
├────────────────────────────────────────────────────────────────────────┤
│  TerminalCard (Pro mode; auto-opens on first cli_subprocess_stream)    │
│  Tabs per CLI platform: claude_code · codex · gemini_cli · copilot ·…  │
└────────────────────────────────────────────────────────────────────────┘
```

Three nested `<ResizableSplit>` instances:

| Level | Direction | Storage key |
|---|---|---|
| Outer chat row vs terminal | horizontal (column split) | `dcc.outer.sizes.<mode>` |
| Chat row → left card · editor groups · activity panel | vertical (row split) | `dcc.chatRow.sizes.<mode>` |
| Editor groups | vertical | `dcc.editor.sizes` |

All sizes persist via localStorage (`apControl.*`, `dcc.*` namespaces). Resize from one device does not pollute another (key includes Pro/Simple `<mode>`).

---

## 2. Left card modes

The left card toggles between two modes — persisted in `apControl.leftMode`:

| Mode | Component | Source |
|---|---|---|
| `chats` | session list | `GET /api/v1/chat/sessions` |
| `files` | workspace file tree | `GET /api/v1/workspace/tree` |

### File tree

Two scopes, picked via a top-of-card switcher:

| Scope | Root | Audience |
|---|---|---|
| **Tenant** | `/var/agentprovision/workspaces/<tenant_id>/` | every authenticated user |
| **Platform** | `/opt/agentprovision/platform-docs/` (curated) | superusers only |

Lazy-loaded — `GET /api/v1/workspace/tree?scope=<>&path=<>` returns one directory at a time. Click a file → `GET /api/v1/workspace/file?scope=<>&path=<>` returns markdown / text. While a file is open the right pane is overridden with `FileViewer` (replaces `AgentActivityPanel` until the user closes the doc).

Workspace volume is provisioned via a named `workspaces` volume in `docker-compose.yml` and a `helm/charts/microservice/templates/workspaces-pvc.yaml` guarded by `workspaces.enabled=true` in `helm/values/agentprovision-api.yaml` (10 GiB default; PR #515).

### Workspace persistence

Both the Files tab and the `code-worker` CLI runtimes share the same per-tenant subtree on the workspaces volume — files Luna writes via memory or via `alpha workspace clone` are visible in the tree on the next refresh, and vice versa. The dashboard's tree is just a read view; **all writes flow through kernel verbs** (`alpha workspace clone` for repos, the recall/record pipeline for memory). Path-segment guards reject `.git/`, `__pycache__/`, etc.; platform scope is superuser-gated; reads cap at 256 KiB.

Full model + endpoint contracts: [`workspace.md`](workspace.md).

---

## 3. Editor groups (chat splits)

The center column supports **1..4 editor groups**, side-by-side. Each group:

- Has its own active session (`apControl.editorGroups[i].sessionId`).
- Shows a 2 px inset `var(--brand-primary)` border when focused.
- Receives the new session when a row in the left card is clicked **while focused**.

State map in localStorage:

```jsonc
"apControl.editorGroups":  [{ "id":"g0", "sessionId":"…" }, …],
"apControl.focusedGroupId": "g0"
```

A planned v2 extension (see split-pane spec doc) adds heterogeneous panes (chat | doc | activity) to the right column with a uniform `<PaneItem>` chrome wrapper.

---

## 4. Pro vs Simple mode

Top-right toggle (`apControl.mode = 'pro' | 'simple'`).

| Visible | Pro | Simple |
|---|---|---|
| Left card | ✓ | ✓ |
| Editor groups | ✓ | ✓ |
| AgentActivityPanel | ✓ | ✗ |
| TerminalCard | ✓ (auto-opens on first stream) | ✗ |

Simple disarms the height chain on small viewports — see §7.

---

## 5. Inline CLI picker

Replaces the prior "Open in full chat" link in the chat thread header. A compact `<InlineCliPicker>` widget (pill button + menu) lets the user pick the active CLI runtime for the **tenant**, writing `tenant_features.default_cli_platform` via `brandingService.updateTenantFeatures`. Tenant-wide effect — every new session uses the picked CLI.

Pattern guidance: prefer compact pill widgets (this one, `<InlineCliPicker>`) over full Alert UI (`<DefaultCliSelector>`) when the choice is contextual to a working surface rather than an explicit settings page.

---

## 6. Live agent activity

Single shared SSE subscription per session via `SessionEventsContext` (PR #500). Eliminates per-pane SSE fan-out (one stream, N consumers).

Event types rendered:

| Event | Surface |
|---|---|
| `chat_message` | EditorArea (chat tab) |
| `tool_call_started` / `tool_call_complete` | AgentActivityPanel |
| `cli_routing_decision` | AgentActivityPanel |
| `cli_subprocess_started` / `cli_subprocess_stream` / `cli_subprocess_complete` | TerminalCard |
| `plan_step_changed` | AgentActivityPanel (inline plan stepper) |
| `subagent_dispatched` / `subagent_response` | AgentActivityPanel |
| `auto_quality_consensus` | AgentActivityPanel |
| `resource_referenced` | AgentActivityPanel |

Backend: `GET /api/v2/sessions/{id}/events` (SSE live tail + paginated replay). Persistence in `session_events` (migration 133). See [`../plans/2026-05-15-alpha-control-plane-design.md`](../plans/2026-05-15-alpha-control-plane-design.md) §5 for the protocol.

---

## 7. Height chain — DOM layering

The terminal must stay on-screen even on small viewports. Achieved with a strict height: 100% chain:

```
.dcc-outer-col       (flex column, viewport-bound)
  └─ .rs-root        (ResizableSplit container)
       └─ .rs-pane   (each pane)
            └─ .dcc-chat-row    (3-column inner row)
                 └─ .ap-card    (card chrome)
                      └─ scroll children
```

Every level is `height: 100%`. The terminal sits in the second `.rs-pane` of the outer split. If any level loses `100%` the chain collapses and the terminal pushes below the fold (regression history: PRs #508, #509, #510).

### Responsive breakpoints

| Width | Behavior |
|---|---|
| ≥ 992 px | full IDE shell, terminal docked |
| 768 – 991 px | left card collapses to icon rail; chat fills |
| < 768 px | height chain **disarmed**; layout stacks; terminal floats above content |

---

## 8. ⌘K command palette

`<CommandPalette>` (`apps/web/src/dashboard/CommandPalette.js`) — unified fuzzy search across:

- Sessions (recent first)
- Agents (tenant fleet)
- Static nav (Workflows, Memory, Integrations, Settings, …)

Wired via `Cmd+K` / `Ctrl+K` global shortcut on `/dashboard`.

---

## 9. ⚡ A2A coalition trigger

`<TriggerCoalitionModal>` opens from the ⚡ button next to the session list. Picks a pattern (`incident_investigation`, `deal_brief`, `cardiology_case_review`, `plan_verify`, `propose_critique_revise`, …) and dispatches `POST /api/v1/collaborations/run`. Live phase timeline streams back into AgentActivityPanel.

---

## 10. localStorage namespace map

| Key | Purpose |
|---|---|
| `apControl.mode` | `'pro'` or `'simple'` |
| `apControl.leftMode` | `'chats'` or `'files'` |
| `apControl.editorGroups` | array of `{ id, sessionId }` |
| `apControl.focusedGroupId` | id of focused editor group |
| `apControl.fileScope` | `'tenant'` or `'platform'` |
| `apControl.rightPane.items` | (v2) heterogeneous pane array |
| `apControl.rightPane.focusedId` | (v2) focused pane id |
| `dcc.outer.sizes.<mode>` | outer split (chat row vs terminal) |
| `dcc.chatRow.sizes.<mode>` | inner row split |
| `dcc.editor.sizes` | editor group splits |
| `dcc.rightPane.sizes` | (v2) inner right-column split |
| `dcc.terminal.openTab` | last-active CLI tab |

---

## 11. Don't-touch zones (multi-agent concurrency)

These files are owned by parallel streams and should not be edited from docs PRs:

- `apps/web/src/dashboard/ResizableSplit.{js,css}` — Phase A landed in PR #518
- `apps/web/src/dashboard/TerminalCard.js` — CLI streaming agent
- `apps/web/src/dashboard/AgentActivityPanel.js` — CLI streaming agent
- `apps/code-worker/cli_runtime.py`, `apps/code-worker/cli_executors/*.py`, `apps/code-worker/workflows.py` — CLI streaming + codex MCP
- `apps/api/app/api/v2/*.py` — CLI streaming agent

---

## 12. References

| Topic | Doc |
|---|---|
| Alpha CLI kernel principle | [`alpha_cli_kernel.md`](alpha_cli_kernel.md) |
| Workspace persistence + endpoints | [`workspace.md`](workspace.md) |
| Three-layer control plane | [`../plans/2026-05-15-alpha-control-plane-design.md`](../plans/2026-05-15-alpha-control-plane-design.md) |
| IDE shell design (canonical) | [`../plans/2026-05-15-alpha-control-center-ide-shell-design.md`](../plans/2026-05-15-alpha-control-center-ide-shell-design.md) |
| Pane composition + doc viewer | [`../plans/2026-05-16-dashboard-split-pane-spec-doc-viewer.md`](../plans/2026-05-16-dashboard-split-pane-spec-doc-viewer.md) |
| Terminal full CLI output | [`../plans/2026-05-16-terminal-full-cli-output.md`](../plans/2026-05-16-terminal-full-cli-output.md) |
| Codex MCP tool access fix | [`../plans/2026-05-16-codex-mcp-tool-access-fix.md`](../plans/2026-05-16-codex-mcp-tool-access-fix.md) |
