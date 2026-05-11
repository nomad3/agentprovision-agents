# Plan — `ap` CLI Multi-Runtime Dispatch Verb (Orchestrator *of CLIs*)

**Date:** 2026-05-11
**Owner:** `apps/agentprovision-cli` + `apps/agentprovision-core`
**Status:** Proposed
**Predecessors:**
- `2026-05-09-agentprovision-cli-design.md` (CLI scaffold)
- `2026-05-10-agentprovision-cli-distribution-plan.md` (Homebrew / GH Releases)
- Phase 4 (agent-token + hook templates — already shipped server-side)

## 1. Strategic frame

`ap` already routes chat *through* the platform (`ap chat send` → `/api/v1/chat/sessions/{id}/messages` → Temporal `ChatCliWorkflow` → one of four CLI executors in `apps/code-worker/cli_executors/`). The platform is the *orchestrator of CLIs* — but only on the server side. From the user's terminal, the four runtimes are inaccessible directly.

This plan adds **local-dispatch verbs** that let a user invoke a chosen runtime *from their terminal* with platform-injected context (agent_token, MCP URL, memory recall, persona prompt, hooks). The runtime runs locally; the platform supplies identity + tools + memory.

This is the lever that closes "orchestrator of CLIs" as a complete user experience: the same context, audit trail, and toolset whether dispatch happens via the server (chat hot path) or via the user's keyboard.

## 2. User-facing surface (clap shape)

Sugar verbs (per-runtime convenience):

```
ap claude-code   <PROMPT> [flags]
ap codex         <PROMPT> [flags]
ap gemini-cli    <PROMPT> [flags]   # also: ap gemini
ap copilot       <PROMPT> [flags]
```

Canonical verb (power-user / scripting):

```
ap run --runtime <claude_code|codex|gemini_cli|copilot_cli> \
       [--agent <slug-or-uuid>] \
       [--use-tenant-token] \
       [--no-memory] [--no-persona] [--no-hooks] [--no-persist] \
       [--cleanup <auto|keep>] \
       [--workdir <path>] \
       <PROMPT>
```

Fan-out (Section 9):

```
ap run --runtimes claude_code,codex,gemini_cli --parallel <PROMPT>
```

## 3. Architecture overview

```
ap claude-code "fix X"
   │
   ├─► (1) resolve_agent_for_runtime  → /api/v1/agents?runtime=claude_code
   ├─► (2) preflight                  → which claude / version / OAuth env
   ├─► (3) mint_agent_token           → POST /api/v1/agent-tokens/mint
   ├─► (4) memory_recall              → GET  /api/v1/memory/recall?query=...
   ├─► (5) build_runtime_context      → MCP config + CLAUDE.md + hooks
   ├─► (6) materialize_workdir        → write .claude.json / .codex/config.toml / .gemini/settings.json / .copilot/mcp-config.json + hooks
   ├─► (7) spawn_subprocess           → tokio::process::Command with injected env, inherited stdio
   ├─► (8) collect_transcript         → tee stdout/stderr (terminal + buffer)
   ├─► (9) on_exit                    → POST /api/v1/chat/sessions/{id}/messages (audit), cleanup workdir
```

## 4. Per-runtime install detection + auth strategy

`agentprovision-core::runtime::preflight` returns a `PreflightReport` per runtime.

### 4.1 Claude Code
- Detect: `which claude`.
- Local auth: `~/.claude/.credentials.json` or `CLAUDE_CODE_OAUTH_TOKEN` env.
- Tenant auth: delegate fetch from user-scoped variant of `oauth/internal/token/claude_code`.
- Install hint: `npm i -g @anthropic-ai/claude-code` (or `curl -fsSL https://claude.ai/install.sh | sh`).

### 4.2 Codex
- Detect: `which codex`.
- Local auth: `~/.codex/auth.json`.
- Install hint: `npm i -g @openai/codex` or `brew install codex`.

### 4.3 Gemini CLI
- Detect: `which gemini`. Floor: 0.37.1+ (per worker).
- Local auth: `GEMINI_API_KEY` or `~/.gemini/oauth_creds.json`.
- Install hint: `npm i -g @google/gemini-cli`.

### 4.4 Copilot CLI
- Detect: `which copilot`.
- Local auth: `GITHUB_TOKEN`/`GH_TOKEN` env or `gh auth status` OK.
- Install hint: `gh extension install github/gh-copilot` or `brew install copilot-cli`.

### 4.5 Auth precedence

| Flag | Local present | Tenant fetchable | Behavior |
|---|---|---|---|
| (none) | yes | — | Local |
| (none) | no | yes | Tenant (with prompt) |
| `--use-tenant-token` | any | yes | Always tenant |
| `--use-tenant-token` | any | no | Error: connect integration or drop flag |

## 5. New core helpers (`agentprovision-core`)

### 5.1 `core::runtime` module

```rust
pub enum RuntimeId { ClaudeCode, Codex, GeminiCli, CopilotCli }

pub struct PreflightReport {
    pub runtime: RuntimeId,
    pub binary_path: Option<PathBuf>,
    pub version: Option<String>,
    pub local_auth_present: bool,
    pub install_hint: &'static str,
}

pub async fn mint_agent_token_for_runtime(
    client: &ApiClient, runtime: RuntimeId, agent_id: &str,
) -> Result<MintedAgentToken>;

pub struct MintedAgentToken {
    pub token: String, pub task_id: String, pub agent_id: String,
    pub expires_at: DateTime<Utc>, pub allowed_tools: Vec<String>,
}
```

### 5.2 **Critical server-side precursor — new endpoint**

The existing `POST /api/v1/internal/agent-tokens/mint` is gated by `X-Internal-Key`; the CLI must never hold that. Add:

```
POST /api/v1/agent-tokens/mint
  Auth: Bearer <user JWT>
  Body: { runtime, agent_id? }
  Behavior:
    1. Resolve agent (default for runtime if not given).
    2. Verify user can dispatch the agent (RBAC).
    3. Create `task` row (origin=cli, requested_by=user_id, runtime=runtime).
    4. Mint via services.agent_token.mint_agent_token(parent_chain=[user_id]).
    5. Return { token, task_id, agent_id, expires_at, allowed_tools }.
```

Rate-limit suggestion: 30/min/user.

### 5.3 Workdir materializers (port from Python)

Per-runtime materializers port `apps/code-worker/workflows.py` `_prepare_*_home` functions + `apps/code-worker/hook_templates.py` to Rust. Files written:

| Runtime | Files |
|---|---|
| Claude Code | `.claude.json` (mode 0600), `.claude/hooks/{pre,post}tooluse.sh`, `.claude/hooks/hooks.json`, `CLAUDE.md` |
| Codex | `.codex/auth.json`, `.codex/config.toml` |
| Gemini | `.gemini/{oauth_creds,credentials,projects,google_accounts,settings}.json` |
| Copilot | `.copilot/mcp-config.json` |

Hooks (PreToolUse + PostToolUse) are Claude-Code-specific; other runtimes rely on server-side scope enforcement at the MCP boundary.

### 5.4 Persona + memory composer

```rust
pub async fn build_persona_prompt(
    client: &ApiClient, agent_id: &str, user_prompt: &str, include_memory: bool,
) -> Result<String>;
```

Fetches agent.system_prompt, optionally recalls top-K memory observations (1500ms cap), composes a CLAUDE.md-style prefix.

**Precursor:** verify `GET /api/v1/memory/recall?query=...&k=...` is exposed as a user-scoped route (apps/api/app/services/memory_recall.py exists; route may already exist — verify).

## 6. New CLI commands (`apps/agentprovision-cli/src/commands/`)

```
src/commands/
  run.rs          # canonical `ap run` + sugar variants
  preflight.rs    # invoked by `ap status` and pre-run gate
  transcript.rs   # buffered stdio tee for audit
```

Flow (single-runtime):

1. preflight ensures binary exists.
2. Resolve agent_id (slug → uuid).
3. Mint agent_token via new user-scoped endpoint.
4. Build composed_prompt (persona + memory).
5. Build runtime_mcp_config.
6. Materialize workdir (mode 0600 on secrets).
7. `tokio::process::Command` spawn — pipe stdout/stderr through transcript tee.
8. Wait for exit; capture exit_code, transcript, duration.
9. POST audit to `/api/v1/chat/sessions/{id}/messages` (skipped with `--no-persist`).
10. Cleanup workdir per `--cleanup` mode.

## 7. Fan-out (`--parallel`)

`ap run --runtimes claude_code,codex,gemini_cli --parallel "..."`:

- `tokio::spawn` per runtime; each runs the full flow concurrently.
- Per-runtime workdir is `<workdir>/.runtime-<id>/` to avoid file conflicts.
- TTY renders side-by-side table with ✓/✗ + duration + token count + final-answer snippet at end.
- `--json` emits `{"results": [...]}`.

## 8. Acceptance criteria

Fresh macOS, `ap claude-code "say hello"`:

1. preflight passes (claude found, version OK).
2. `POST /api/v1/agent-tokens/mint` returns JWT in <500ms.
3. `GET /api/v1/memory/recall` returns within 1500ms (or skip cleanly on timeout).
4. `.claude.json` mode 0600 with `Authorization: Bearer <jwt>`.
5. `.claude/hooks/{pre,post}tooluse.sh` chmod 0755, registered in hooks.json.
6. claude subprocess spawned with `AGENTPROVISION_*` env trio set; `CLAUDE_CODE_OAUTH_TOKEN` unset (local auth path).
7. User sees streamed reply.
8. On exit: POST audit, cleanup workdir, propagate exit code.

`ap claude-code --use-tenant-token "..."` without tenant Claude Code integration → fast fail with actionable message.

`ap codex "..."` without `codex` installed → exit 2 + install hint, no API calls made.

## 9. PR breakdown

- **PR-1 (M, 3-4 days):** core::runtime module + new server endpoints (`POST /agent-tokens/mint` user-scoped, `GET /memory/recall` if missing) + `ap run --runtime claude_code` MVP + `ap claude-code` sugar.
- **PR-2 (S, 1-2 days):** Codex / Gemini / Copilot runtimes.
- **PR-3 (S, 1 day, post-MVP):** `--parallel` fan-out + TTY side-by-side renderer.

## 10. Risks + open questions

1. User-scoped mint endpoint design — RBAC + rate-limit + task-row creation.
2. Hooks on non-Claude runtimes — wait for upstream PreToolUse equivalents; rely on server scope-claim until then.
3. Local-auth detection false positives — let runtime fail naturally; surface hints only on `--use-tenant-token` failure.
4. Workdir secrecy — all four runtimes need 0600 on token-bearing files. Add regression test.
5. Cleanup on Ctrl-C — register `tokio::signal::ctrl_c` handler + `Drop` guard on `CleanupTracker`.
6. Cost / quota for tenant tokens — surface "this counts against your plan" banner.
7. Memory recall on `--no-persona` — suppress memory too (noise without context).

## 11. Test plan

- Unit (Rust): workdir-materializer parity tests vs `apps/code-worker/tests/test_prepare_homes.py` fixtures.
- Unit (Python): new server endpoints — auth gate, agent-tenant ACL, task row.
- Integration: stub `claude` binary with a tiny shell script that emits JSON; assert env / workdir / cleanup invariants.
- Acceptance: `scripts/cli/test-run-verb.sh` runs all four sugar verbs against local API with stubbed binaries.

## Critical files for implementation

- `apps/agentprovision-cli/src/cli.rs`
- `apps/agentprovision-core/src/lib.rs`
- `apps/code-worker/hook_templates.py` (port to Rust verbatim)
- `apps/code-worker/workflows.py` (`_prepare_*_home` ports)
- `apps/api/app/api/v1/internal_agent_tokens.py` (reuse, add user-scoped sibling)
- `apps/api/app/services/memory_recall.py` (verify user-scoped route exists)

## Alignment note (per 2026-05-11 user directive)

This plan must not duplicate hook templates, mcp config materialization, or persona-prompt composition that already exist server-side. Implementation ports the Python helpers to Rust **verbatim** (string constants for hook bodies, identical config-file shapes) so the user-side runtime and the server-side worker produce byte-identical workdirs. Workdir-parity test asserts this.
