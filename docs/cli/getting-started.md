# Getting started with `alpha` (v0.7.5)

This is the 10-minute tour. By the end you'll have logged in, confirmed
auth, dispatched all three primary delegation patterns, and know where
to look when something breaks.

For the full reference, see [README.md](README.md). For known issues,
see [troubleshooting.md](troubleshooting.md).

## 1. Install

```bash
# macOS / Linux
curl -fsSL https://agentprovision.com/install.sh | sh

# Windows (PowerShell)
iwr https://agentprovision.com/install.ps1 | iex
```

Drops the `alpha` binary into `~/.local/bin/` (POSIX) or
`%USERPROFILE%\.agentprovision\bin\` (Windows). No sudo, no admin.

Verify:

```bash
alpha --version
# alpha 0.7.5
```

If you have a previous version installed, run `alpha upgrade` and then
read the [`alpha upgrade lost my auth`](troubleshooting.md#alpha-upgrade-lost-my-auth)
note — v0.7.5 restored OS keychain as the default token store, so
upgrades from v0.7.4 may need a fresh `alpha login`.

## 2. Authenticate

```bash
alpha login
```

By default this attempts the **device-code flow**: the CLI prints a URL
and a short code, you open the URL in a browser, paste the code, and
the CLI picks up the resulting bearer token automatically. The token
lands in the OS keychain (macOS Keychain / Linux Secret Service /
Windows Credential Manager).

If the backend's device-flow endpoint isn't reachable, or you're in CI,
fall back to password auth:

```bash
# Interactive password prompt
alpha login --password

# Pre-filled email
alpha login --password --email me@example.com

# CI: password from environment
echo "$AP_PASSWORD" | alpha login --email "$AP_EMAIL" --password-stdin
```

Token TTL is roughly 30 minutes — long enough for a session, short
enough that re-login is part of the daily rhythm.

## 3. Verify

```bash
alpha status
```

You should see your email, tenant id, the resolved server URL, and the
CLI version. Add `--runtimes` to also preflight Claude Code, Codex,
Gemini CLI, Copilot CLI, and OpenCode against their standard credential
paths.

If `alpha status` says `authenticated: no`, the token expired — rerun
`alpha login`.

## 4. The three primary delegation patterns

`alpha` is the orchestrator-of-CLIs. Every command you run flows through
the agentprovision.com control plane, which dispatches to the right
runtime — Temporal workflows, MCP tool calls, A2A coalitions — under
the hood.

The three patterns below cover the bulk of day-to-day use. They differ
in **how long the turn takes** and **whether the LLMs must agree**.

### Pattern A — `alpha chat send` (short turns, single LLM, streaming)

For one-off questions and quick chats. Streams tokens as the model
generates them.

```bash
alpha chat send "summarise yesterday's lead pipeline"
alpha chat send "draft a discovery email" --agent <agent_uuid>
alpha chat send "what about the second one?" --session <session_uuid>
```

Backed by SSE over HTTPS through Cloudflare. **Idle streams get cut
around the 524 deadline**, so for multi-minute turns use Pattern B
below.

### Pattern B — `alpha run --fanout` (long turns, durable, resumable)

Dispatches into Temporal's `agentprovision-code` queue. Survives
terminal close, network drop, laptop reboot. Resume from any other
host on the same account.

```bash
# Single-provider fanout — the 90% case. SHIPPED today (PR #573).
alpha run --fanout claude_code "refactor app/api/v1/reports.py into typed handlers" --background

# Multi-provider parallel fanout. SHIPPED; --merge council/all still
# returns raw child outputs as a list while LLM adjudication is queued.
alpha run --fanout claude_code,codex,gemini_cli "audit auth for SQLi" --merge council --background

# Tail the task from anywhere
alpha watch <task_id>

# Or cancel it
alpha cancel <task_id>
```

`--background` returns `{task_id, status:queued}` immediately. Without
`--background`, the CLI tails in the foreground until completion or
`--timeout` (default 1800s / 30 min — the task itself keeps running
on the backend, just resume with `alpha watch`).

The flag `USE_REAL_FANOUT_WORKFLOW=true` must be set in `apps/api/.env`
for real dispatch. It's enabled in production; self-hosters need to
flip it.

> Not yet wired to real Temporal dispatch: plain `alpha run "..."`
> (no `--fanout`), and `alpha run --providers a,b,c` fallback chains —
> both still hit the Phase-1 synthetic stub. Use `--fanout <single-cli>`
> as the workaround. See
> [`docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`](../plans/2026-05-18-alpha-cli-delegation-pattern.md)
> for the queued Phase-3 work.

### Pattern C — `alpha review start` (cross-CLI consensus, code review)

Fans the same review prompt out to N active CLIs and surfaces only
findings ≥ 2 of them agree on. Loop with `alpha review reply` until
consensus = "no agreed findings" or `--max-rounds` is exhausted.

```bash
# Quote the # — it's a shell comment marker otherwise
alpha review start "#570" --clis claude_code,codex,gemini_cli --max-rounds 3
alpha review status <review_id>
alpha review reply <review_id> "#570-rev2"
alpha review watch <review_id>           # SSE; Cloudflare cuts ~100s, re-run
alpha review list --status awaiting_response
```

You can also pipe a diff in via `--stdin`:

```bash
gh pr diff 570 | alpha review start --stdin --clis claude_code,codex
```

> **Known issue:** the fire-and-forget Temporal dispatcher in
> `apps/api/app/services/review_dispatch.py::_runner` silently fails to
> start the workflow (daemon thread + `asyncio.run` race). The
> consensus aggregator, table, and event surface are fully live —
> drive the loop manually by POSTing each CLI's output to
> `POST /reviews/{id}/record` until the hotfix lands. Recipe in
> [troubleshooting.md](troubleshooting.md#review-stays-running-no-findings).

## 5. Where to go next

- [`docs/cli/README.md`](README.md) — full command reference including
  `alpha agent`, `alpha workflow`, `alpha memory` / `alpha recall` /
  `alpha remember`, `alpha skill`, `alpha integration`, `alpha coalition`,
  `alpha recipes`, `alpha tasks`, `alpha usage` / `alpha costs`,
  `alpha upgrade`, `alpha completions`, `alpha quickstart`.
- [`docs/cli/troubleshooting.md`](troubleshooting.md) — every known issue
  in v0.7.5 with workarounds.
- [`docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`](../plans/2026-05-18-alpha-cli-delegation-pattern.md) —
  the design that ties patterns A/B/C together and lists Phase 3 extensions.
- [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](../plans/2026-05-13-ap-cli-differentiation-roadmap.md) —
  the full eight-feature CLI roadmap and where we are in it.
