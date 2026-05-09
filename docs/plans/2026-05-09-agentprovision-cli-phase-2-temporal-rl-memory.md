# Plan — `agentprovision` CLI Phase 2: Temporal Compatibility + CLI Pool + RL + Memory

**Owner:** PR-C+ scope of the CLI rollout (after PR-A core extraction + PR-B login/chat skeleton)
**Why:** Phase 1 (the original CLI design plan) ships login + chat + status as a thin client. That's a good baseline. Phase 2 makes the CLI **a peer runtime in the AgentProvision orchestration plane** — the same way Claude Code, Codex, Gemini CLI, and GitHub Copilot CLI are runtimes the platform's autodetect/quota-fallback chain dispatches to. The new `agentprovision` CLI joins that pool, gets RL + memory benefits, and dispatches Temporal workflows directly.

This plan extends `docs/plans/2026-05-09-agentprovision-cli-design.md`. Read that first.

## Goal

Make the new `agentprovision` CLI fully compatible with:

1. **Temporal worker pool** — `agentprovision workflow run / status / tail` dispatches against `agentprovision-orchestration` queue using the same `temporalio` client the API uses. `agentprovision agent run` for code-task style work dispatches against `agentprovision-code` queue.
2. **CLI runtime pool** — the platform's CLI-resolver (which today picks across Claude Code / Codex / Gemini CLI / GitHub Copilot CLI per `tenant_features.default_cli_platform` + autodetect) recognizes `agentprovision` itself as another runtime. Tenants can opt to route specific agents through the local `agentprovision` CLI (useful when the user is running the CLI on their own machine and wants their own subscription / context to do the work).
3. **RL pipeline** — every CLI invocation logs an `rl_experience` row with `decision_point='cli_invocation'`, state (subcommand, args summary, tenant, agent_id), action (which runtime served the response), reward (latency + success + auto-quality score). Over time the CLI improves: which subcommand the user reaches for in which context becomes a learned routing signal, exposed back via aliases / suggestions.
4. **Memory pipeline** — every chat invocation pre-loads memory context the same way the API's hot path does, via the existing `recall()` service through the new `agentprovision-core::memory` module. Every CLI conversation contributes to the user's memory graph (the user is talking to *their own* AgentProvision tenant; memory accumulates).

## Deliverables

### Phase 2A — Temporal worker pool integration

1. **`agentprovision-core::temporal` module** — wraps `temporalio` Python is API-side; the CLI core in Rust uses a thin gRPC client against `temporal:7233` directly OR delegates to the API's `/workflows/runs` REST surface (preferred — the API enforces tenant scoping).
2. **CLI subcommands wired:**
   - `agentprovision workflow run <name> [--input KEY=VAL]` — POSTs to `/api/v1/workflows/{name}/runs` (or by ID); returns `run_id`. With `--watch`, immediately tails events.
   - `agentprovision workflow status <run-id>` — GETs run state.
   - `agentprovision workflow tail <run-id>` — SSE follow of `/api/v1/workflows/runs/{id}/events`. Streams step-by-step output with progress bars (indicatif).
   - `agentprovision workflow logs <run-id>` — fetches step-level output via `/workflows/step-logs?run_id=...`.
   - `agentprovision agent run <slug> --prompt <text> [--watch]` — for `cli_execute` style invocations that dispatch a `CodeTaskWorkflow` on `agentprovision-code` queue.
3. **Live demo** — `agentprovision workflow run multi-site-revenue-sync --watch` produces real-time step output in the terminal as Luna walks through pull → consolidate → deliver.

### Phase 2B — CLI runtime pool

1. **Backend change**: `tenant_features.default_cli_platform` already accepts `claude_code | codex | gemini_cli | copilot_cli`. Add `agentprovision_local` as a 5th option. When set, agent dispatches that hit the autodetect chain prefer the `agentprovision_local` runtime when the request originates from an `agentprovision` CLI session (recognized via a new `X-AgentProvision-Runtime: cli/<version>` header on the API client).
2. **Local-runtime dispatch**: when the API routes a chat through `agentprovision_local`, instead of spawning `claude` / `gemini` / `codex` subprocesses on a code-worker pod, it returns the prompt + tool schema to the CLI client, which performs the LLM call locally using the user's machine credentials (Claude Pro subscription, OpenAI key, etc.) and streams the response back via WebSocket. This is **opt-in, off-by-default** — only fires when both (a) the request comes from an `agentprovision` CLI client and (b) the tenant has `agentprovision_local` in the autodetect chain.
3. **Why this matters**: VMG owners who already pay for Claude Code Pro / OpenAI Plus can have their AgentProvision agents *use their own subscription* during interactive CLI sessions instead of burning the platform's quota. Cleanly separates platform-paid from user-paid runtime cost.
4. **`apps/api/app/services/agent_router.py`** — extend the runtime-resolver to know about `agentprovision_local` and emit it in the autodetect chain when appropriate.
5. **`apps/api/app/services/cli_session_manager.py`** — add the `agentprovision_local` runtime to `CLIProvider` enum + dispatch path.

### Phase 2C — RL pipeline integration

1. **`agentprovision-core::telemetry` module** — every CLI invocation collects:
   - subcommand path (`workflow run`, `chat send`, `agent run`, etc.)
   - arg summary (no PII; lengths + flags only)
   - tenant_id, agent_id (when known)
   - latency total, latency-to-first-token (for streaming subcommands)
   - exit code / error class
   - auto-quality score (when applicable, e.g. chat sends already get scored by the Gemma 4 council)
2. Telemetry is sent to a new endpoint `POST /api/v1/rl/internal/cli-experience` (uses `X-Internal-Key` plus the user's session token for tenant binding). The API translates the CLI experience into an `rl_experience` row with `decision_point='cli_invocation'`.
3. **Privacy model**: prompt content is NEVER sent unless the tenant has explicitly opted in via `tenant_features.cli_telemetry_full_prompt = true` (default false). The default telemetry is: subcommand, latency, success/failure, auto-quality score — enough for routing and improvement, no content.
4. **What this unlocks**:
   - **Learned aliases**: after 50 invocations of `agentprovision chat send "show me yesterday's revenue"`, the platform suggests `agentprovision alias add yesterday-revenue 'chat send "show me yesterday'\''s revenue"'`.
   - **Subcommand routing improvements**: if a user keeps falling back from `workflow run` to `agent run` (because the workflow they wanted was actually an agent task), the platform learns the correction and surfaces a hint.
   - **Failure pattern detection**: if `workflow run multi-site-revenue-sync` fails with the same tenant-side data-source error 5 times, the CLI proactively surfaces "this workflow has been failing — last error was X — see fix in `agentprovision integration test covetrus_pulse`".

### Phase 2D — Memory pipeline integration

1. **`agentprovision-core::memory` module** — wraps the existing `/memory/recall` and `/memory/observation` endpoints. CLI subcommands:
   - `agentprovision memory recall <query>` — returns top-K observations (already in the Phase 1 plan; now wired through core).
   - `agentprovision memory observe <text> [--entity <name>] [--type <observation_type>]` — records a new observation. Useful for daily reflections (`echo "Q1 revenue beat target by 8%" | agentprovision memory observe --entity 'Animal Doctor SOC'`).
2. **Chat hot-path memory pre-load**: when the user runs `agentprovision chat send "what did I work on yesterday"`, the CLI calls the API's chat endpoint with a `prefer_memory_context=true` flag (already supported); the API's existing `recall()` pre-loads the relevant entities + observations into the CLAUDE.md context before the LLM call. The CLI displays a small `📚 5 memories recalled` line in the streaming output to surface what was loaded.
3. **Cross-device memory continuity**: because memory lives server-side, the same user running `agentprovision chat` from their laptop on Monday and from a customer's clinic on Wednesday gets the same memory context. Every invocation contributes back. This is identical to how the Tauri Luna client works today — same memory graph, different surface.
4. **Memory-driven CLI suggestions**: `agentprovision suggest` (new subcommand) uses memory recall against the user's current context to surface "based on your last 7 days of work, you might want to: [1] re-run the bookkeeper export for week-of, [2] check if the BrightLocal Sentinel surfaced new ranking gaps, ...".

## Architecture: how the CLI joins the orchestration plane

```
User's terminal
    │
    ├── agentprovision chat send "..."
    │       └── agentprovision-cli (Rust binary)
    │               └── agentprovision-core (Rust lib)
    │                       ├── auth (keychain)
    │                       ├── client (reqwest → api.agentprovision.com/...)
    │                       ├── memory (calls /memory/recall + /memory/observation)
    │                       ├── telemetry (POST /rl/internal/cli-experience after each cmd)
    │                       └── temporal (calls /workflows/.../runs for workflow subcommands)
    │
    └── HTTPS → api (FastAPI) → ChatService.post_user_message
            ├── memory.recall() pre-loads context
            ├── runtime resolver picks `agentprovision_local` if tenant configured + CLI runtime header present
            ├── if agentprovision_local: WebSocket back to CLI for the actual LLM call (uses user's local creds)
            ├── else: Temporal dispatch to code-worker (same as today — Claude Code / Codex / etc.)
            ├── auto_quality_scorer scores the response → rl_experience row
            └── stream response back to CLI → CLI renders markdown via termimad
```

## Dependencies + sequencing

- **Phase 1 PR-A (core extraction)** must land first — Phase 2 depends on `agentprovision-core` existing.
- **Phase 1 PR-B (login + chat + status skeleton)** must land before Phase 2A — workflow subcommands need the auth + client modules.
- **Phase 2A (Temporal)** can ship in parallel with Phase 2C (RL telemetry) — they touch different modules.
- **Phase 2B (CLI runtime pool)** is the most invasive — touches `agent_router.py`, `cli_session_manager.py`, the runtime enum, and the autodetect chain. Ship after 2A + 2C are stable so the WebSocket-back path has the rest of the CLI to lean on.
- **Phase 2D (memory)** is the smallest — wire-up only, no backend changes; recall + observe endpoints exist.

Recommended PR sequence:
- **PR-C**: workflow + agent subcommands (Phase 2A) + memory subcommands (Phase 2D)
- **PR-D**: RL telemetry (Phase 2C) — privacy-first default
- **PR-E**: CLI runtime pool (Phase 2B) — the strategic-feature flagship
- **PR-F**: distribution (Homebrew tap + GitHub Releases — original Phase 1 PR-D, slips here so PR-E can land)

## Definition of Done

- ✅ `agentprovision workflow run/status/tail/logs` works end-to-end against the live `agentprovision-orchestration` queue
- ✅ `agentprovision agent run` dispatches `CodeTaskWorkflow` on `agentprovision-code` queue and tails it
- ✅ `agentprovision_local` is a valid value for `tenant_features.default_cli_platform`; agents route through it when a CLI client is the requester AND the tenant opted in
- ✅ Every CLI invocation produces an `rl_experience` row with `decision_point='cli_invocation'`
- ✅ Memory recall pre-loads on `agentprovision chat send`; CLI surfaces "📚 N memories recalled"
- ✅ `agentprovision suggest` returns memory-driven suggestions for the user's current context
- ✅ All PRs assigned to nomad3, no AI credit lines
- ✅ End-to-end test scenarios pass:
  1. `agentprovision workflow run multi-site-revenue-sync --watch` shows live step output
  2. `agentprovision chat send "what did I work on this week"` returns memory-grounded answer
  3. After 20 invocations, `agentprovision suggest` returns at least one usable suggestion
  4. Tenant flagged with `default_cli_platform=agentprovision_local`, running CLI with login → chat send: response generated locally using user's Claude/OpenAI subscription, then logged to RL with `served_by_platform='agentprovision_local'`

## Risks

- **PR-E (CLI runtime pool) WebSocket-back path** is the most architecturally invasive change. It requires careful auth on both directions of the WebSocket and a clean fallback if the CLI disconnects mid-call. May spill into a follow-up PR-E.5.
- **Privacy on RL telemetry** — must default to no-content. A bug here leaks customer prompts to the platform's own training corpus. Needs explicit opt-in test coverage.
- **Memory pre-load latency** — adds 80-200ms to every chat send. Acceptable for `chat send`; might be too slow for `chat` REPL turns. Consider lazy/parallel pre-load.
- **Backend `agentprovision_local` runtime requires the API to push a prompt out to a CLI client over WebSocket** — that's an inverted control flow (today, the API is always the request-handler, never the request-issuer). Architecturally legal but new.

## Cross-references

- Phase 1 plan: `docs/plans/2026-05-09-agentprovision-cli-design.md`
- Existing CLI runtime resolver: `apps/api/app/services/cli_session_manager.py` + `apps/api/app/services/agent_router.py`
- Existing RL pipeline: `apps/api/app/services/rl_experience_service.py` + `auto_quality_scorer.py`
- Existing memory: `apps/api/app/memory/recall.py` + `record.py`
- Temporal worker: `apps/api/app/workers/orchestration_worker.py` + `apps/code-worker/`
- The Modern Animal / Sierra research note (PR #320) flagged conversation-replay regression as our biggest stack gap vs Sierra — RL telemetry from the CLI is one of the inputs that feeds into closing that gap (`docs/research/2026-05-09-modern-animal-harriet-sierra.md` §5)
