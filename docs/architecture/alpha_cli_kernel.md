# Alpha CLI as Kernel

**Status:** Architectural principle (2026-05-16). Applies to every new feature.
**Origin:** [`../plans/2026-05-15-alpha-control-plane-design.md`](../plans/2026-05-15-alpha-control-plane-design.md) §2
**Followed by:** Dashboard, Tauri, WhatsApp, MCP-as-leaf, future channels.

---

## 1. Principle

> **Every feature flows through Alpha CLI.**
> Frontend → CLI (kernel) → internal API → MCP tools / memory / RL.

The CLI is not a convenience wrapper. It is the **engine** that every viewport (web `/dashboard`, Tauri, WhatsApp, terminal, MCP-leaves) consumes. One brain, many viewports.

```
┌──────────────────────────────────────────────────┐
│  CHANNELS  (viewports onto the orchestrator)     │
│  alpha CLI │ Web /dashboard │ Tauri │ WhatsApp   │
└──────────────────────────────────────────────────┘
                      ↕  /api/v2/sessions/{id}/events
┌──────────────────────────────────────────────────┐
│  MESH  (A2A coalition · blackboard · handoffs)   │
└──────────────────────────────────────────────────┘
                      ↕
┌──────────────────────────────────────────────────┐
│  KERNEL  (alpha CLI as engine, cloud-resident)   │
│  CLI fleet routing │ vault │ memory │ MCP tools  │
│  workflows │ skills │ RL store                   │
└──────────────────────────────────────────────────┘
```

Whether the user types in a terminal, the Web Dashboard, the Tauri app, or WhatsApp, the request lands at the same orchestrator code path. Deployment-topology note: in local-dev the kernel runs as the `api` / `orchestration-worker` / `code-worker` containers in docker-compose; in production the same containers run in the cloud. "Kernel" is a logical layer, not a Kubernetes-specific assumption.

---

## 2. Why this matters

Three failure modes this principle prevents:

1. **Surface drift.** A feature added to the web SPA without going through the CLI becomes web-only. Tauri, WhatsApp, and `alpha` CLI users silently lose it.
2. **Memory + RL gaps.** Skip the kernel and you skip `recall()`, you skip `record_*()`, you skip the auto-quality scorer. The feature is unobservable for RL.
3. **Authn / authz fragmentation.** The vault, tenant scoping, and agent-scoped JWTs live in the kernel. Frontend-direct paths to MCP or DB invariably re-implement (and weaken) the auth model.

If a new feature can't be expressed as `alpha <verb>`, the design is wrong.

---

## 3. Concrete examples

### 3.1 Workspace file tree (`/dashboard` Files mode)

The Files mode in the dashboard left card lists tenant + platform files. The frontend does **not** read the disk. It calls a thin API that wraps the kernel verb:

```
Web /dashboard  ──HTTP──▶  GET /api/v1/workspace/tree?scope=tenant&path=…
                                        │
                                        ▼
                          ┌──────────────────────────────┐
                          │  alpha workspace tree …      │  (kernel verb)
                          └──────────────────────────────┘
                                        │
                                        ▼
                              filesystem  (jailed to scope root)
```

Same verb is reachable from the terminal (`alpha workspace tree --scope tenant /docs`), Tauri (Rust shells out), WhatsApp (`/workspace tree …`), and an MCP leaf (`read_workspace_file` tool). Adding a new scope (e.g. shared-team) means adding one kernel verb — every viewport gets it.

### 3.1.1 Workspace clone — write verb on the same volume

`alpha workspace clone <owner/repo>` is the canonical kernel-routed way to seed a tenant's project tree.

```
Web /dashboard  ──HTTP──▶  POST /api/v1/workspace/clone {owner, repo}
                                        │
                                        ▼
                          ┌──────────────────────────────┐
                          │  alpha workspace clone …     │
                          └──────────────────────────────┘
                                        │  background task
                                        ▼
                          git clone inside code-worker
                          (mounts the same /var/agentprovision/workspaces volume)
                                        │
                                        ▼
                          /var/agentprovision/workspaces/<tenant_id>/projects/<repo>/
                                        │
                                        ▼
                          publish_session_event("workspace_repo_cloned", …)
                                        │
                                        ▼
                          v2 SSE  →  dashboard tree refresh
```

Note the loop: the `code-worker` mounts the **same** named volume as `api`, so the clone shows up in the dashboard tree (which reads via `api`) without any cross-service file copy. The frontend never invokes `git`. Identical reachability from terminal (`alpha workspace clone …`), Tauri, WhatsApp, and MCP leaves.

Full model: [`workspace.md`](workspace.md).

### 3.2 Chat send

The dashboard chat-input box does not write to PostgreSQL. It calls:

```
Web /dashboard  ──HTTP──▶  POST /api/v1/chat/sessions/{id}/messages
                                        │
                                        ▼
                          ┌──────────────────────────────┐
                          │  alpha chat send …           │
                          └──────────────────────────────┘
                                        │
                          recall() → CLAUDE.md → cli_session_manager
                                        │
                          Temporal · code-worker · CLI runtime
                                        │
                          publish_session_event(...)  →  v2 SSE
                                        │
                          PostChatMemoryWorkflow (entity extraction, async)
                                        │
                          auto_quality_scorer (RL experience)
```

Every consumer (web, Tauri, WhatsApp, leaf agents) hits the same path. Auto-scoring is automatic.

### 3.3 Workflow run

```
alpha workflow run incident_investigation --json
       └─ identical to:  POST /api/v1/workflows/{id}/run
              └─ DynamicWorkflowExecutor (Temporal)
                     └─ steps emit session_events → live in /dashboard
```

### 3.4 Leaf agents call back **into** the kernel via MCP

A code-worker leaf (Claude Code, Codex, Gemini, Copilot) is *itself* a channel. It calls back into the kernel via the agentprovision MCP server (`apps/mcp-server`) over SSE with an agent-scoped JWT. Same backend endpoints either way — CLI binary for humans in terminals, MCP tool surface for leaves.

See memory: `leaf_agent_inbound_via_mcp.md`.

---

## 4. Anti-patterns

Avoid these. If you see them in a PR, reject and route through the CLI.

| Anti-pattern | Why bad | Right pattern |
|---|---|---|
| Frontend writes to a new DB table directly via a one-off `/api/v1/foo` POST | Skips memory, skips RL, skips audit | Define `alpha foo <verb>`, route the HTTP through it |
| Component opens its own SSE connection per render | N×SSE fan-out, dropped reconnect logic | Single `SessionEventsContext` subscription, consumer hooks |
| Tauri Rust talks directly to PostgreSQL / Redis | Bypasses tenancy, vault, RBAC | Tauri calls the kernel verb via HTTP |
| WhatsApp handler grows a special-case prompt path | Drifts from web behavior | Same `alpha chat send` path, channel = `whatsapp` |
| MCP tool surfaces a new capability that has no `alpha` subcommand | Power users can't script it; future viewports can't either | Add the verb, then expose as MCP tool wrapping it |

---

## 5. Implementation checklist for a new feature

1. **Name the verb.** `alpha <noun> <action>`. If you can't, the feature has no business in the kernel layer.
2. **Backend route is thin.** A v1 HTTP handler that delegates to the same Python entrypoint the `alpha` binary calls. No business logic in the route.
3. **Frontend calls the v1 route.** Never the raw DB / Redis / filesystem.
4. **Persist to session_events.** Use `publish_session_event(...)` for anything a human or other agent might want to watch. Single SSE consumer pattern (see `SessionEventsContext` in `apps/web/src/dashboard/`).
5. **RL hook.** If the feature makes an autonomous decision, log an `rl_experience`.
6. **MCP exposure if a leaf needs it.** Wrap the verb as a tool in `apps/mcp-server/src/mcp_tools/<area>.py`.

---

## 6. References

| Topic | Doc |
|---|---|
| Three-layer control plane | [`../plans/2026-05-15-alpha-control-plane-design.md`](../plans/2026-05-15-alpha-control-plane-design.md) |
| IDE shell design | [`../plans/2026-05-15-alpha-control-center-ide-shell-design.md`](../plans/2026-05-15-alpha-control-center-ide-shell-design.md) |
| Dashboard architecture | [`dashboard.md`](dashboard.md) |
| Workspace persistence + endpoints | [`workspace.md`](workspace.md) |
| `alpha` CLI reference | [`../cli/README.md`](../cli/README.md) |
| Leaf-agent inbound (MCP) | memory: `leaf_agent_inbound_via_mcp.md` |
