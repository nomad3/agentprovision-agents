# `alpha` — AgentProvision CLI Reference

The `alpha` binary is the AgentProvision command-line client. It lets you log in,
chat with agents (streaming or REPL), run dynamic workflows, browse the
knowledge graph, manage skills, and inspect tenant integrations — all from
your terminal, with the same backend the web SPA uses.

Cross-platform: macOS (arm64 + x86_64), Linux (x86_64), Windows (x86_64).
Releases auto-update via `alpha upgrade`. Sources live under
`apps/agentprovision-cli` and `apps/agentprovision-core`.

**Current CLI version:** v0.7.5 (released 2026-05-18). Newcomers should
start with the dedicated [getting-started guide](getting-started.md); known
issues live in [troubleshooting](troubleshooting.md).

## Contents

1. [Install & first login](#install--first-login)
2. [Global options](#global-options)
3. [Commands](#commands)
   - [`alpha login` / `alpha logout` / `alpha status`](#alpha-login--alpha-logout--alpha-status)
   - [`alpha chat` — streaming + REPL](#alpha-chat--streaming--repl)
   - [`alpha run` — durable Temporal-backed tasks](#alpha-run--durable-temporal-backed-tasks)
   - [`alpha watch` / `alpha cancel`](#alpha-watch--alpha-cancel)
   - [`alpha review` — cross-CLI consensus reviews](#alpha-review--cross-cli-consensus-reviews)
   - [`alpha agent`](#alpha-agent)
   - [`alpha workflow`](#alpha-workflow)
   - [`alpha session`](#alpha-session)
   - [`alpha memory` / `alpha recall` / `alpha remember`](#alpha-memory--alpha-recall--alpha-remember)
   - [`alpha skill`](#alpha-skill)
   - [`alpha integration`](#alpha-integration)
   - [`alpha coalition`](#alpha-coalition)
   - [`alpha recipes`](#alpha-recipes)
   - [`alpha tasks`](#alpha-tasks)
   - [`alpha usage` / `alpha costs`](#alpha-usage--alpha-costs)
   - [`alpha upgrade`](#alpha-upgrade)
   - [`alpha completions`](#alpha-completions)
   - [`alpha quickstart`](#alpha-quickstart)
4. [Common workflows / recipes](#common-workflows--recipes)
5. [Scripting + CI use](#scripting--ci-use)
6. [Environment variables & token storage](#environment-variables--token-storage)
7. [Troubleshooting](#troubleshooting) — also see [troubleshooting.md](troubleshooting.md)

---

## Install & first login

```bash
# macOS / Linux (recommended one-liner)
curl -fsSL https://agentprovision.com/install.sh | sh

# Windows (PowerShell)
iwr https://agentprovision.com/install.ps1 | iex

# After install
alpha login                     # password flow; --password optional
alpha status                    # confirm authenticated + which tenant
```

The token is stored in the OS keychain on macOS / Windows / Linux (Secret
Service). On systems without a keychain, `alpha` falls back to a plain file at
`$AGENTPROVISION_TOKEN_FILE` if set, or
`~/Library/Application Support/agentprovision/tokens/<host>.token` on macOS
(equivalent XDG path on Linux).

JWTs expire after ~30 minutes. `alpha status` reports `authenticated: no` once
the token has expired; rerun `alpha login`.

---

## Global options

Every command accepts these flags:

| Flag | What |
|---|---|
| `--server <URL>` | Override the API host. Default `https://agentprovision.com`. Also takes `AGENTPROVISION_SERVER` env var. |
| `--json` | Emit machine-readable JSON instead of the pretty tabular renderer. Required for piping into `jq` / scripts. |
| `--no-stream` | For commands that stream by default (`alpha chat send`, `alpha chat repl`), wait for the full reply before printing. Useful in CI and `&&`-chained scripts where partial output would interleave. |
| `-v` / `-vv` | Increase verbosity. `-v` is INFO, `-vv` is DEBUG. Logs go to stderr so JSON on stdout stays parseable. |
| `-h` / `--help` | Per-command help. |
| `-V` / `--version` | Print the CLI version. |

---

## Commands

### `alpha login` / `alpha logout` / `alpha status`

#### `alpha login`

```bash
alpha login                                # interactive: prompts email + password
alpha login --email me@example.com         # email pre-filled
alpha login --password-stdin               # read password from stdin (CI)
alpha login --password-env PW_VAR          # read password from $PW_VAR
alpha login --password                     # force password flow (skip device-flow if present)
```

Stores the bearer token in the OS keychain and writes the tenant/user IDs to
the CLI's resolved context. Token is ~30 min TTL.

#### `alpha logout`

Removes the stored token. Safe to run anywhere.

#### `alpha status`

```bash
alpha status                # default: who am I, tenant, server, CLI version
alpha status --runtimes     # adds preflight for all 5 local CLI runtimes
alpha status --json         # machine-readable
```

`--runtimes` spawns one `--version` subprocess per runtime
(Claude Code, Codex, Gemini CLI, GitHub Copilot CLI, OpenCode). Adds ~100–400ms;
omitted by default because most users just want to confirm auth.

### `alpha chat` — streaming + REPL

#### `alpha chat send <PROMPT>`

One-shot prompt with **streaming response** (Claude-Code-style — tokens land
in the terminal as the assistant generates them).

```bash
alpha chat send "what's in my knowledge graph about competitors?"

# Pin to a specific agent
alpha chat send "draft a discovery email" --agent <agent_uuid>

# Continue an existing session
alpha chat send "what about the second one?" --session <session_uuid>

# Disable streaming (waits for full reply — better for `command | jq`)
alpha chat send --no-stream "give me a JSON summary" --json

# Set a title on the freshly-created session
alpha chat send "stand-up brief" --title "Daily standup 2026-05-12"
```

Without `--session`, every `send` creates a fresh chat session. Use
`--session` to chain multiple `send` calls into the same conversation
(history is preserved server-side).

#### `alpha chat repl`

Interactive multi-turn chat (Gemini-CLI-style continuous session).

```bash
alpha chat repl                            # fresh session
alpha chat repl --session <session_uuid>   # resume an existing session
alpha chat repl --agent <agent_uuid>       # pin a fresh session to an agent
alpha chat repl --no-stream                # wait for full reply per turn
```

Type your message, press Enter; the assistant streams its reply. `Ctrl-D` or
`Ctrl-C` exits. History persists across REPL exits — use `alpha session ls` to
find the session id and `alpha chat repl --session …` to come back.

> **Long prompts:** `alpha chat send` streams over SSE through Cloudflare,
> which cuts idle streams around the 524 deadline. For multi-minute turns
> use `alpha run --fanout <cli> --background` instead — durable Temporal,
> resumable from any host. See [troubleshooting.md](troubleshooting.md#cloudflare-524-on-alpha-chat-send).

### `alpha run` — durable Temporal-backed tasks

Dispatches a long-running task into Temporal's `agentprovision-code` queue.
Unlike `alpha chat send` (synchronous, SSE), `alpha run` survives terminal
close, network drop, and laptop reboot — resume from any other host with
`alpha watch <task_id>`.

```bash
# Single-provider fanout (one CLI, durable Temporal child workflow). SHIPPED today.
alpha run --fanout claude_code "refactor app/api/v1/reports.py into typed handlers" --background

# Multi-provider fanout. Phase 2 lite — multiple providers spawn N child
# workflows in parallel; `--merge council/all` aggregation is wired but
# returns raw child outputs as a list today (council adjudication is queued).
alpha run --fanout claude,codex,gemini "audit the auth module" --merge council --background

# Fallback chain (sequential, quota-aware). NOT YET real-dispatched —
# this path still hits the Phase-1 synthetic stub (see open follow-ups).
alpha run --providers claude,codex,opencode "scaffold the orders service"

# Foreground tail with a custom deadline (default 1800s / 30 min).
alpha run --fanout claude_code "write the migration plan" --timeout 7200

# JSONL event stream for CI / supervisors.
alpha run --fanout claude_code "..." --events ./events.jsonl --background
```

**What's actually shipped (v0.7.5 / PR #573):**

| CLI flag shape | Backend path | Status |
|---|---|---|
| `--fanout <single-cli>` | Real `FanoutChatCliWorkflow` (N=1) | LIVE under `USE_REAL_FANOUT_WORKFLOW=true` |
| `--fanout a,b,c` | Real `FanoutChatCliWorkflow` (N=k, first-wins child) | LIVE; `--merge council/all` still returns raw list |
| `--providers a,b,c` | Synthetic Phase-1 stub | NOT real-dispatched yet — see follow-ups |
| (neither flag) | Synthetic Phase-1 stub | NOT real-dispatched yet — single-provider via `--fanout <cli>` is the workaround |
| `--background` | Returns `{task_id, status:queued}` immediately | LIVE |
| `--timeout N` | CLI honours the foreground deadline | LIVE on the CLI tail; not yet plumbed to Temporal `execution_timeout` (fixed at 180m server-side) |
| `--agent <UUID>` | Propagated to backend | Accepted but **not** yet pushed into `ChatCliInput` (worker logs a warning, runs as tenant default) |
| `--events <path>` | JSONL event sink | LIVE for state transitions; child-CLI tokens not yet routed through it |

The single-provider 90% case is `alpha run --fanout claude_code "..."`
(or codex / gemini_cli / copilot / opencode). Plain `alpha run "..."` and
`alpha run --providers ...` still hit the Phase-1 synthetic stub; planned
fix tracked in `docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`
Phase 3.

The flag `USE_REAL_FANOUT_WORKFLOW=true` is set in `apps/api/.env` for
production. Self-hosters need to flip it for real dispatch.

### `alpha watch` / `alpha cancel`

```bash
alpha watch <task_id>        # tail an in-flight task from any machine
alpha cancel <task_id>       # request cancellation (parent + all fanout children)
```

`alpha watch` polls workflow status until a terminal state. The
underlying Temporal SDK upgraded to `temporalio>=1.10` in PR #575 —
`WorkflowExecutionDescription` is now flat (no `.workflow_execution_info`
attribute); upgrading the server-side worker is required before
`alpha watch` works against a stale orchestration pod.

`alpha cancel` issues `RequestCancelWorkflowExecution`. The leaf CLI
subprocess may take several seconds to observe the signal — Temporal
cancellation is cooperative, not preemptive.

### `alpha review` — cross-CLI consensus reviews

`alpha review` fans the same review prompt out to N active CLIs and
returns only findings that ≥ 2 of them agree on. Operator fixes the
agreed findings, replies with the new ref, loops until consensus
("no agreed findings") or `--max-rounds` is exhausted.

```bash
# Dispatch a review against PR #570. NOTE the quotes — `#` is a shell comment.
alpha review start "#570" --clis claude_code,codex,gemini_cli --max-rounds 3

# By commit SHA / path range / piped diff
alpha review start abc123def --clis claude_code,codex
alpha review start "apps/api/main.py:42-100" --clis claude_code,codex
gh pr diff 570 | alpha review start --stdin --clis claude_code,codex

# Inspect / iterate / tail
alpha review status <review_id>
alpha review reply <review_id> "#570-rev2"
alpha review watch <review_id>             # SSE; Cloudflare cuts at ~100s, re-run to resubscribe
alpha review list --status awaiting_response --limit 20
```

Findings render as a list of clusters with their `cli_set`:

```
agreed_findings:
  1. [BLOCKER]   apps/api/main.py:42-50 — SQL injection in login query
                 (flagged by: claude_code, codex)
  2. [IMPORTANT] apps/api/auth.py:7 — missing input validation
                 (flagged by: claude_code, codex, gemini_cli)
```

**Backed by:** `reviews_coalitions` table (migration 139), the existing
Blackboard substrate, and `ReviewWorkflow` on the
`agentprovision-orchestration` queue. Subcommand surface and consensus
aggregator are fully live (PR #574). Worker-side activity execution
requires the `activity_executor` ThreadPool patch from PR #577.

**Known issue (workaround documented):** the fire-and-forget Temporal
dispatcher in `apps/api/app/services/review_dispatch.py::_runner` (daemon
thread + `asyncio.run`) silently fails to start the `ReviewWorkflow`.
While a hotfix is in flight, drive the consensus loop directly by
POSTing each CLI's output to `POST /reviews/{id}/record` — full recipe
in [troubleshooting.md](troubleshooting.md#review-stays-running-no-findings).

### `alpha agent`

```bash
alpha agent ls                              # all agents in tenant
alpha agent ls --role "sales"               # case-insensitive substring on role
alpha agent ls --status production          # draft / staging / production / deprecated
alpha agent show <uuid_or_name>             # full agent record + governance fields
```

Agent names are tenant-unique (enforced by the `idx_agents_tenant_name_unique`
partial index), so `alpha agent show luna` works without a UUID.

### `alpha workflow`

```bash
alpha workflow ls                           # all dynamic workflows in tenant
alpha workflow ls --status active           # draft / active / paused / archived
alpha workflow ls --trigger cron            # cron / interval / webhook / event / manual / agent

alpha workflow show <id_or_name>            # full definition + run stats
alpha workflow runs <id_or_name>            # recent runs (default 20)
alpha workflow runs <id_or_name> --limit 5

# Trigger
alpha workflow run <id_or_name>             # fire with empty input
alpha workflow run <id_or_name> --input '{"customer_id": "abc"}'
alpha workflow run <id_or_name> --dry-run   # validate definition; no Temporal dispatch

# Lifecycle
alpha workflow activate <id_or_name>        # draft → active
alpha workflow pause <id_or_name>           # active → paused
```

`--dry-run` mirrors the web "Test" button: walks the definition through the
validator without scheduling. Catches step-id collisions, unknown tool names,
and unresolved template references.

### `alpha session`

```bash
alpha session ls                            # newest-first, last 20 sessions
alpha session ls --limit 50                 # cap rows
alpha session ls --title "standup"          # case-insensitive substring filter

alpha session messages <session_uuid>        # last 50 turns (default)
alpha session messages <session_uuid> --all  # full history
alpha session messages <session_uuid> --limit 10
```

Per-message rendering includes a `[<n>tok $<cost>]` trailer when the
code-worker callback measured token + cost (newer messages only). Footer
reports per-session aggregate:

```
[09:30:14] assistant [856tok $0.0042]: hi there
[09:30:33] assistant [612tok $0.0029]: …
── 1468 tokens across 2 measured turns · $0.0071 across 2 priced turns
```

`—` for unmeasured turns (older rows / agents without a usage struct / local
CLIs that don't compute cost — OpenCode + gemma4 leaves cost NULL).

### `alpha memory` / `alpha recall` / `alpha remember`

Three subcommands cover three reads against the memory layer:

| Command | Surface | Returns |
|---|---|---|
| `alpha memory` | Knowledge-graph entities only | Entity rows + observations |
| `alpha recall` | Unified semantic search across entities, observations, episodes, and conversation snippets | The same shape the chat agent queries before every turn |
| `alpha remember` | Write a free-form observation (optionally pinned to an entity) | Saves + embeds for semantic recall |

```bash
# Unified semantic recall (chat-agent parity)
alpha recall "what's our standard FastAPI error handler pattern?"
alpha recall "rhone stores" --limit 10

# Write a fact — Phase 2 (#179) companion to `alpha recall`
alpha remember "we standardized on httpx for outbound HTTP — never requests"
alpha remember "Project Atlas runs on the GTM rebuild team" --entity "Project Atlas"
```

Browse the tenant's knowledge graph (entities + observations).

```bash
alpha memory ls                             # newest first, 25 per page
alpha memory ls --limit 50 --skip 25        # paginate
alpha memory ls --entity-type person
alpha memory ls --category competitor

alpha memory search "rhone"                 # name + description text + pgvector embedding match
alpha memory search "deals at risk" --entity-type project

alpha memory observe --name "Q2 forecast"   # record a new entity
alpha memory observe --name "Project Atlas" \
                  --entity-type project \
                  --description "Internal tracking for the GTM rebuild" \
                  --tags "internal,gtm,2026"
```

`memory search` uses the same pipeline the chat-side auto-recall uses — text
ILIKE with pgvector embedding fallback when `GOOGLE_API_KEY` is set.

`memory observe` is the casual note-taking entry point — defaults to
`entity_type=concept` so you can stash anything without thinking about the
taxonomy.

### `alpha skill`

```bash
alpha skill ls                              # all skills (native + tenant + community)
alpha skill ls --tier native                # bundled with the platform
alpha skill ls --tier custom                # tenant-authored
alpha skill ls --tier community             # imported / shared
alpha skill ls --category coding
alpha skill ls -q "extract entities"        # pgvector + text search
```

The `-q` search hits the same embedding pipeline the chat-side auto-trigger
uses to pick skills mid-conversation.

### `alpha integration`

```bash
alpha integration ls                        # every integration the platform knows about
alpha integration ls --connected            # only what the tenant has connected
```

Lists per-tenant connection status for Gmail, Calendar, GitHub, WhatsApp,
Slack (when configured), Meta/Google/TikTok ads, and the other 30+ registered
integrations.

> **Known issue:** the server currently returns a map shape that the CLI
> deserializer expects as an array, so `alpha integration ls` fails with a
> serde error. CLI-side fix queued for the next release; see
> [troubleshooting.md](troubleshooting.md#alpha-integration-ls-fails-with-a-serde-error).

### `alpha coalition`

Multi-agent coalitions on the existing `CoalitionWorkflow` /
`Blackboard` substrate (shipped 2026-04-12). Patterns include incident
investigation, plan/verify, research/synthesize, debate/resolve, and
propose/critique/revise.

```bash
alpha coalition list                           # available patterns
alpha coalition run incident-investigation --severity P1 --service orders-api
alpha coalition watch <coalition_id>           # tail Blackboard SSE
```

### `alpha recipes`

The "Helm charts for AI workflows" surface — pre-built dynamic
workflows (daily briefings, competitor watch, code review, cardiac
report, deal pipeline, ...) installable by name.

```bash
alpha recipes ls
alpha recipes install <id>
alpha recipes run <id>
alpha recipes run <id> --schedule "0 8 * * 1-5"
```

### `alpha tasks`

Cross-machine task dashboard for the current tenant — every working
and recently-completed workflow run for the caller's account.

```bash
alpha tasks ls                                 # working + completed
alpha tasks attach <task_id>                   # alias for `alpha watch`
alpha tasks cancel <task_id>                   # alias for `alpha cancel`
```

`needs-input` task surfacing is deferred to a follow-up (see the
agent-view design doc).

### `alpha usage` / `alpha costs`

Per-provider token rollup and per-day cost rollup. Both default to
the current tenant; scope down with `--agent <uuid>`.

```bash
alpha usage --period mtd
alpha costs --agent <agent_uuid> --period 7d
```

Phase 4 of the CLI roadmap; backed by the per-task `cost_usd` +
input/output token columns shipped in #174.

### `alpha upgrade`

Self-updates the `alpha` binary from GitHub Releases.

```bash
alpha upgrade                # latest stable, prompts before replacing
alpha upgrade -y             # skip the confirmation prompt (CI / scripts)
alpha upgrade --check        # dry-run: report whether an update exists; exit 0
alpha upgrade --version 0.7.0  # pin a specific version (allows downgrade)
alpha upgrade --prerelease   # follow pre-release channel (reserved — no releases there today)
```

Resolves the install method (Homebrew formula, cargo install, direct binary
under `~/.local/bin`) and uses the appropriate update path. Reports the path
in stdout so you can `which alpha` to confirm.

### `alpha completions`

```bash
alpha completions bash       > ~/.local/share/bash-completion/completions/alpha
alpha completions zsh        > "${fpath[1]}/_ap"
alpha completions fish       > ~/.config/fish/completions/alpha.fish
alpha completions powershell > $PROFILE.CurrentUserAllHosts
alpha completions elvish     > ~/.config/elvish/lib/alpha.elv
```

Run once after install or after `alpha upgrade` lands a new top-level command.

### `alpha quickstart`

Guided initial-training flow. **Auto-fires** the first time you `alpha login`
against a fresh tenant; can be re-run explicitly to re-train or to opt back
in after Skip.

```bash
alpha quickstart                                 # interactive picker
alpha quickstart --channel local_ai_cli          # skip picker; scan local AI CLI history
alpha quickstart --channel github_cli            # scan repos / orgs / PRs via gh
alpha quickstart --channel gmail                 # server-side Gmail bootstrap (needs OAuth)
alpha quickstart --channel calendar              # server-side Calendar bootstrap (needs OAuth)
alpha quickstart --force                         # re-train even when tenant is already onboarded
alpha quickstart --resume                        # resume an interrupted run via persisted snapshot_id
alpha quickstart --no-chat                       # don't fire the first chat at the end
alpha quickstart --no-stream                     # disable streaming for the post-training chat
alpha quickstart --no-topic-hints                # local_ai_cli only: skip the topic-hint excerpt
```

Channels:

| Channel | Source |
|---|---|
| `local_ai_cli` | Claude / Codex / Gemini / OpenCode session metadata + git config |
| `github_cli` | `gh api` / `gh search` against your authed account (repos, orgs, PRs, issues) |
| `gmail` | Server-side Gmail fetch (last 7d, metadata-only, dedup'd on sender) |
| `calendar` | Server-side Calendar fetch (next 14d, attendees as Person entities) |
| `slack` | Stub — needs the Slack OAuth sprint |
| `whatsapp` | Stub — needs the neonize-aio surface refactor |

Resume state is persisted at
`~/.config/agentprovision/quickstart-<tenant_id>.toml` so a Ctrl-C mid-run
can be picked back up with `--resume`.

---

## Common workflows / recipes

### 1. Quick chat with streaming

```bash
alpha login                                                 # once
alpha chat send "summarise my last 5 customer interactions"
```

### 2. Interactive REPL with a specific agent

```bash
alpha agent ls --status production
alpha chat repl --agent <luna_uuid>
> who are my top 3 priority leads this week?
> ^D
```

### 3. Resume a previous chat session

```bash
alpha session ls --title "Q2 forecast"
# → grab the id from the table
alpha chat repl --session 4f8a...
```

### 4. Trigger a workflow with structured input

```bash
alpha workflow ls --status active
alpha workflow run "Lead Pipeline" --input '{"source": "linkedin", "limit": 25}'
alpha workflow runs "Lead Pipeline" --limit 5         # see the run that just landed
```

### 5. Validate a workflow before activating

```bash
alpha workflow run "Daily Briefing" --dry-run
alpha workflow activate "Daily Briefing"
```

### 6. Browse + capture knowledge

```bash
alpha memory search "rhone stores"
alpha memory observe --name "Rhone PR launch" \
                  --entity-type concept \
                  --category competitor \
                  --description "Spring 2026 product reveal — track" \
                  --tags "competitor,signal"
```

### 7. Confirm an integration before automating against it

```bash
alpha integration ls --connected            # is Gmail green?
alpha workflow run "Inbox Triage"
```

### 8. JSON for piping

```bash
alpha session ls --json | jq '.[] | {id, title, created_at}'
alpha memory search "investor" --json | jq '.[].id' | head -5
alpha workflow runs "Lead Pipeline" --json --limit 10 | jq '[.[] | .duration_ms] | add / length'
```

### 9. End-to-end smoke test of a new agent

```bash
alpha agent show "MyAgent"
alpha chat repl --agent <uuid>
> introduce yourself
> what tools do you have access to?
> ^D
alpha session ls --limit 1                  # confirm the session landed
```

### 10. CI / scripted login

```bash
echo "$AP_PASSWORD" | alpha login --email "$AP_EMAIL" --password-stdin --json
alpha workflow run "Nightly Sync" --json
```

---

## Scripting + CI use

- Use `--json` on every command you parse — the pretty renderer is for humans.
- Use `--no-stream` on `alpha chat send` so partial output can't interleave with
  later shell pipeline stages.
- Use `--password-stdin` or `--password-env` to keep secrets out of process
  argv (which is world-readable on most systems via `/proc`).
- `AGENTPROVISION_TOKEN_FILE` is honoured for headless environments without a
  keychain (Docker, CI runners). Point it at a tmpfs path, write the token
  via `alpha login --json | jq -r .access_token > "$AGENTPROVISION_TOKEN_FILE"`.
- Exit codes follow the standard contract: 0 = success, non-zero = failure
  (with a stderr message). Use `set -e` safely.

---

## Environment variables & token storage

| Variable | Purpose |
|---|---|
| `AGENTPROVISION_SERVER` | Default server URL (e.g. `https://staging.agentprovision.com`). Overridable per-invocation via `--server`. |
| `AGENTPROVISION_TOKEN_FILE` | Where to read/write the bearer token if the OS keychain isn't available. Used by Docker / CI / headless tests. |
| `NO_COLOR` | Standard convention — disables ANSI colour in the pretty renderer. |
| `RUST_LOG` | Fine-grained log filter (e.g. `RUST_LOG=alpha=debug`). Pairs with `-vv`. |

Token storage locations (in priority order):

1. `$AGENTPROVISION_TOKEN_FILE` if set
2. OS keychain (macOS Keychain Services / Windows Credential Manager / Linux Secret Service via libsecret)
3. `~/Library/Application Support/agentprovision/tokens/<host>.token` (macOS fallback)
4. `~/.config/agentprovision/tokens/<host>.token` (Linux XDG fallback)

> **v0.7.5 upgrade note:** OS keychain is once again the default backend.
> Users running `alpha upgrade` from v0.7.4 may need to `alpha login` again —
> the token store path changed and the old plaintext fallback is no longer
> auto-discovered. See [troubleshooting.md](troubleshooting.md#alpha-upgrade-lost-my-auth).

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for the full and current list
including v0.7.5-specific issues (review-dispatch threading bug, integration
ls serde error, post-upgrade token-store path change, Cloudflare 524 on
long chats). The entries below are the legacy quick-fixes.

### `error: authentication required` immediately after running a command

Token expired (~30 min TTL). Run `alpha login` again.

### `alpha status --runtimes` shows `auth: no` for a runtime that's installed

That column reflects whether a **local credentials file** exists at the
runtime's standard path (e.g. `~/.claude/.credentials.json`,
`~/.codex/auth.json`). If the runtime expects a different path, the CLI is
conservative and reports `no` — the runtime may still work via a tenant
token; the column is informational.

### `alpha chat send` hangs with no output

If the command works against the API directly but the CLI hangs, try
`--no-stream` — some terminals (notably older xterm builds) buffer SSE
chunks until newline. `--no-stream` waits for the full reply server-side.

### `alpha workflow run` returns 422

The validator rejected something. Re-run with `--dry-run` to get the
validator's full error list before the dispatch attempt.

### `alpha memory search` returns nothing for a query you expect to match

`pgvector` similarity has a minimum-score floor; very-short queries or
queries against a near-empty graph return empty. Try `alpha memory ls
--entity-type <type>` to confirm the graph has anything for that type.

### Token file is gone after a reboot but no `alpha logout` was run

macOS: the token lives in your Keychain — check Keychain Access → search
"agentprovision". If you see it but `alpha status` says no, the key derivation
may have flipped; `alpha logout && alpha login` clears it.

### `alpha upgrade` fails on Apple Silicon with a `Bad CPU type` error

The macOS binary is universal2 (arm64 + x86_64); if Rosetta isn't installed
on a fresh M-series Mac the loader can't run the x86_64 slice some
intermediate tool ran during install. `softwareupdate --install-rosetta` and
re-run `alpha upgrade`.

---

## Source / development

| Path | What |
|---|---|
| `apps/agentprovision-cli/` | Rust CLI binary (clap-based). Top-level `alpha` entrypoint and all subcommands. |
| `apps/agentprovision-core/` | Shared core crate. API client, runtime detection, training-scanner library, serde models. |
| `apps/agentprovision-cli/src/commands/` | One file per command. Read the file to see the exact backend calls. |
| `.github/workflows/cli-build-matrix.yaml` | Cross-platform build (Mac arm64/x86, Windows, Linux). |
| `.github/workflows/cli-release.yaml` | GitHub Releases on tag push. |
| `tests.yaml` rust matrix | `cargo test` on `agentprovision-core` + `agentprovision-cli`. |

To hack on the CLI locally:

```bash
cd apps/agentprovision-cli
cargo build --release --bin alpha
./target/release/alpha status
```

Set `AGENTPROVISION_SERVER=http://localhost:8000` to point a freshly-built
binary at your local docker-compose stack.
