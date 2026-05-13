# PR-C alignment recon — what already exists

Recon performed 2026-05-10 before implementation dispatch.

## agentprovision-core methods that ALREADY EXIST (don't duplicate)

  - `list_agents()` — already in client.rs:172
  - `get_tenant(id)` — client.rs:179
  - `list_chat_sessions()` — client.rs:185
  - `list_chat_messages(session_id)` — client.rs:191
  - `create_chat_session(...)` — client.rs:201
  - `send_chat_message(session_id, content)` — client.rs:220
  - `list_workflows()` — client.rs:231
  - `get_workflow_run(run_id)` — client.rs:237
  - `login_password(email, password)` — auth.rs:195
  - `request_device_code(client)` — auth.rs:200
  - `poll_device_token(client, device_code)` — auth.rs:236
  - `complete_device_flow(...)` — auth.rs:276

## Models that ALREADY EXIST

  - Token, User, Tenant, Agent, ChatSession, ChatMessage, ChatTurn, Workflow, WorkflowRun, DeviceCodeResponse

## Agent struct is THIN — extend with care

```rust
pub struct Agent {
    pub id: Uuid, pub name: String,
    pub role: Option<String>, pub description: Option<String>,
    pub status: Option<String>,
}
```

Missing fields PR-C might want: tool_groups, persona_prompt, default_model_tier, version, owner_user_id. Add via `#[serde(default)]` so older releases stay forward-compatible.

## Workflow struct is THIN

Same pattern — needs definition_id, last_run, is_template. Add with serde(default).

## Net for the PR-C plan

  - PR-C-1 was going to add list_agents + list_workflows + get_workflow_run → ALREADY DONE. C-1 reduces to: get_agent, create_agent, run_agent (composite), run_workflow, list_workflow_runs, cancel_workflow_run, plus tail_workflow_run SSE-or-polling. ~half the core work the plan listed.
  - PR-C-4 was going to add list_chat_sessions + list_chat_messages → ALREADY DONE. C-4 reduces to get_chat_session(id) + delete_chat_session(id).
  - The CLI side is largely unchanged — it still needs to wire up the new subcommands and the output renderer.

## User-behaviour alignment — read these web pages before designing each verb

| CLI verb | Web equivalent | Backend endpoints used |
|---|---|---|
| `alpha agent ls / show` | `apps/web/src/pages/AgentsPage.js` | GET /api/v1/agents |
| `alpha agent create` | `apps/web/src/components/wizard/AgentWizard.js` | POST /api/v1/agents (5-step wizard — match field names) |
| `alpha workflow ls / run` | `apps/web/src/pages/WorkflowsPage.js` + `workflows/RunsTab.js` | GET /workflows, POST /dynamic-workflows/{id}/run |
| `alpha workflow tail` | `apps/web/src/components/workflows/RunTreeView.js` | polling today (verify SSE endpoint) |
| `alpha integration ls / show / test` | `apps/web/src/pages/IntegrationsPage.js` + `IntegrationsPanel.js` | GET /integrations/status, /integration-configs |
| `alpha memory recall / observe` | `apps/web/src/pages/MemoryPage.js` | GET /memories/search, POST /memories |
| `alpha skill ls / show / run` | `apps/web/src/pages/SkillsPage.js` | GET /skills/library, POST /skills/library/execute |
| `alpha session ls / resume` | `apps/web/src/pages/ChatPage.js` | GET /chat/sessions |

Implementation agents MUST read the web equivalent before writing the CLI surface so field names, validation rules, and UX semantics match.

## Test alignment

  - Existing pattern: `wiremock` mock server (already used in PR-B for chat tests).
  - Don't introduce new mock frameworks. Don't write Python-style backend tests for CLI flows.

## Unchanged constraints from PR-C plan

  - 4 chained sub-PRs (C-1 → C-2 → C-3 → C-4)
  - Output renderer extension for table/yaml/tsv (no existing one — net new)
  - Slash command dispatch must share handlers via a trait (per the plan)
  - AGENTPROVISION.md + @-file refs (net new)
  - Aliases (net new)

## Backend precursors confirmed

  - `mcp.rs` URL bug in core is real — `POST /api/v1/mcp` JSON-RPC is the actual surface (apps/api/app/api/v1/mcp_bridge.py).
  - `GET /api/v1/users/me/tenants` does not exist; add as part of C-3.
  - `system_prompt` on POST /chat/sessions: needs verification before C-4.
  - SSE for workflow runs: needs verification; polling fallback in C-1 is acceptable.

## Status of plan persistence

The original Plan-agent output was inline-returned (read-only mode). Saved verbatim to `docs/plans/2026-05-11-ap-cli-pr-c-subcommands-plan.md` so implementation agents can reference. This recon doc is its alignment overlay.
