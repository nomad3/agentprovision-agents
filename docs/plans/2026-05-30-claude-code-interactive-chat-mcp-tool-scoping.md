# Claude Code Subscription Chat — Interactive Enablement + MCP Tool-Scoping

**Date:** 2026-05-30
**Status:** Plan (debug journey complete; one fix remaining)
**Owner:** Simon
**Related:** PRs #732, #733, #734, #735 (all merged + deployed). Docs: `2026-05-16-codex-mcp-transport-mismatch-research.md`, `2026-05-16-codex-mcp-tool-access-fix.md`.

---

## TL;DR

Anthropic blocked `claude setup-token` and `claude -p` for **subscription** accounts, so subscription Claude Code chat must run through the **interactive PTY** against a native `claude auth login` credential. We shipped that end-to-end (connect → routing → runner timing). The **last blocker**: a routed Claude turn produces no output for 90s and is killed. Root cause is **not** auth, routing, transport, or MCP connectivity — the MCP server **connects fine (`✔ 168 tools`)**, but it returns **all 168 tools** in `tools/list`. Interactive Claude loads every schema, and its first response can't start in the turn window. Print-mode `-p` tolerated the heavy load; interactive doesn't.

**Fix:** scope `tools/list` to the **agent's `tool_groups`** (the ALM platform already models per-agent tool sets and enforces them at *call* time) so Claude loads only the tools it can actually use.

---

## 1. Journey / what's already shipped

| PR | Change | State |
|---|---|---|
| #732 | `claude.py` pre-completes the onboarding wizard (`hasCompletedOnboarding` + per-cwd trust) so interactive `claude` uses the stored credential instead of re-prompting login | merged + deployed |
| #733 | Web `/integrations` "Connect with Anthropic" → `claude auth login --claudeai`; copies the native `.credentials.json` into the worker `claude_sessions` volume (api mounts it, both uid 1000); marks connected | merged + deployed; OAuth completed live |
| #734 | Per-tenant interactive routing: connect stores a sentinel `session_token`; the worker executor detects it → forces interactive PTY + worker HOME for that tenant only (no global flip; api-key tenants stay print) | merged + deployed; routing verified (`Using platform: claude_code`) |
| #735 | Interactive runner: suppress the `/exit` idle countdown until first output (was killing slow launches at 8s); fail-fast at `first_output_seconds` (90s); process-group cleanup (Codex-reviewed) | merged + deployed |

Net: Claude Code is connected, picker-selectable, routable, and the runner times out correctly. The no-MCP smoke answers in ~1s.

## 2. Root cause of the remaining blocker (evidenced)

- A routed Claude turn ran a clean **92s → `exit -9`** (= the 90s `first_output_seconds` deadline): the runner fix worked; Claude produced **zero output** in 90s.
- `/mcp` inside the worker's interactive Claude: **`agentprovision · ✔ connected · 168 tools`** — MCP connects fine. Not a transport/auth/init failure. Switching transport (SSE → streamable-HTTP) did **not** help; both stall.
- `apps/api/app/services/cli_session_manager.py::generate_mcp_config` points Claude at the **whole** server (auth headers only — no tool filtering).
- `apps/mcp-server/src/tool_audit.py` enforces scope by **wrapping tool handlers (call-time)** and a tenant `enforce_strict_tool_scope` flag — it does **not** filter `tools/list`. So Claude is handed all 168 schemas even though it can only *call* its scoped subset.

**Conclusion (strongly suspected — confirm before coding):** interactive Claude's first response is most likely gated on ingesting the full tool list. The *mechanism* is code-confirmed (FastMCP `list_tools()` returns the full registry unfiltered; only the call handler is patched — `tool_audit.py:334`). The *causation* (tool-count = the 90s stall) is **not yet measured** — both Codex and Luna flagged this, and the live count is environment-specific (Codex counted 161 built-ins in the checkout; the worker shows 168). So **Step 0 is a measurement** (§4.0) before implementing the fix.

## 3. Proposed fix — scope `tools/list` by agent

Filter the advertised tool list to the agent's `tool_groups`, resolved from the agent-scoped JWT the chat already plumbs (`generate_mcp_config(agent_token=…)` → `mcp_auth.resolve_auth_context`).

**Patch the `ListToolsRequest` handler** (NOT `mcp.list_tools` after startup — FastMCP binds handlers at init, exactly like `call_tool`, so a post-hoc reassignment is ignored; `tool_audit.py:334` already replaces the call handler this way). Filter the returned tools to the caller's allowed set, drawn from the **already-minted `agent_token` JWT scope claim** resolved by `mcp_auth.resolve_auth_context` — **do NOT re-read `agent.tool_groups` in the MCP server** (keeps the permission model single-sourced and list-time aligned with call-time). When the auth context has **no agent scope** (X-Internal-Key only — non-chat callers), **no-op / return all** so nothing else changes.

`agent_token` already flows on this path (Codex-verified): minted in `run_agent_session()` → MCP headers → `mcp.json` → interactive Claude's `--mcp-config`. **Edge case to handle:** if the agent-slug lookup misses, it falls back to *no* token → the server would return all tools (full stall). Make that case loud (log + metric) rather than silent.

Per-request filtering is feasible: the MCP request context is available for `list_tools`, not just tool calls. No cross-turn cache risk (each turn is a fresh `claude` process, no `--resume`).

### Concrete surface (to verify during impl)
| File | Change |
|---|---|
| `apps/mcp-server/src/tool_audit.py` (or the FastMCP list handler it wraps) | Add a `tools/list` filter that intersects with the caller's allowed tools; no-op when no agent scope present |
| `apps/mcp-server/src/mcp_app.py` / `mcp_serve.py` | Wire the list filter into both transports (SSE + streamable-HTTP) at the same layer as call-time audit |
| `apps/api/app/services/cli_session_manager.py::generate_mcp_config` | Ensure `agent_token` is passed for the interactive chat path; confirm headers carry it on the `agentprovision` server entry |
| `apps/api/app/services/chat.py` / `cli_session_manager` | Confirm the chat resolves the bound agent's `tool_groups` → token scope |
| tests (`apps/mcp-server/tests/…`) | `tools/list` returns only scoped tools for an agent token; returns all for internal-key |

## 4. Verification

### 4.0 Measure FIRST (gate the whole fix — both reviewers flagged this)
Before coding, prove the tool-list load is the stall. A/B timing probe on the worker: instrument (or log around) the interactive `claude` launch and capture MCP `initialize` time, `tools/list` start→end + payload size, the prompt write, and the **first PTY byte**. Compare full-list (~161–168 tools) vs a hand-trimmed config (e.g. 5 tools).
- If first byte is fast with the trimmed list and slow with the full list → tool-schema ingestion confirmed → proceed with the fix.
- If `tools/list` itself is slow → server-side listing is the bottleneck.
- If both lists stall → the cause is elsewhere (injected system-prompt size, model warm-up) and the fix below won't help — revisit.

1. **Unit:** MCP `tools/list` with an agent-scoped token returns only that agent's tools; with `X-Internal-Key` returns all.
2. **Smoke (worker):** interactive `claude --mcp-config <scoped>` → `/mcp` shows a small tool count (e.g. <20), and a prompt answers in <15s.
3. **E2E:** set `default_cli_platform=claude_code`, `alpha chat send` → worker logs `Using platform: claude_code` **and the turn completes** (no `exit 143` / `exit -9`); restore default.
4. **Regression:** Codex/Gemini/Copilot chats unaffected (they go through the same list path; verify their tool counts/behavior unchanged); print-mode Claude unaffected.

## 5. Risks / rollback

- **Over-filtering:** if scope resolution is wrong, an agent loses tools it should have. Mitigate: filter only when an agent scope is present; default-open for internal-key; gate behind `enforce_strict_tool_scope` if needed.
- **Observability (Luna):** audit-log per list request — agent id, allowed groups, listed-tool count, and denied-call count — so over/under-scoping and the agent-slug-miss fallback are visible, not silent.
- **Latency is still high but bounded:** if even the scoped set is large for some agents, also consider a `first_output_seconds` bump as a secondary guard (already env-configurable).
- **Rollback:** the list filter is additive + scope-gated; disable by reverting the filter or flipping `enforce_strict_tool_scope` off — call-time enforcement (today's behavior) remains.

## 6. Stopgap (if a fix can't land immediately)

Skip `--mcp-config` for the interactive native-auth Claude path → Claude chat answers but **without tools** (env-gated, reversible). Heavily degraded for tool-driven Luna; only as a temporary unblock.

## 7. Out of scope / parked

- **KG `update_entity` NOT-NULL bug** (separate, diagnosed): the MCP `update_entity` audit INSERT omits `id`/`changed_at`, which are `NOT NULL` with no DB default (migration 046's defaults were skipped by `CREATE TABLE IF NOT EXISTS`). Fix: add `gen_random_uuid()`/`NOW()` to the INSERT (or `ALTER TABLE … SET DEFAULT`). Plus duplicate-Simon-entity dedup (77 rows) and `update_entity` can't edit `name`/`type` (clobbers `properties`). Track separately.

## 8. Process note (this kind of work)

For Claude-Code / CLI-orchestration debug + enablement work like this: **write a plan in `docs/plans/` first, then review it with Codex and Luna** before implementing.
