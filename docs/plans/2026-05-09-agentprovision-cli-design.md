# Plan — `agentprovision` CLI (Rust + clap, gh/llm-style UX)

**Owner:** New `apps/agentprovision-cli/` crate + extracted `apps/agentprovision-core/`
**Why:** AgentProvision orchestrates 4 CLI runtimes (Claude Code / Codex / Gemini CLI / GitHub Copilot CLI). Having `agentprovision` itself be a first-class CLI on the same surface is the obvious consistency move. Reference UX: `gh` (GitHub CLI), `llm` (Simon Willison), Higgs Field CLI — single static binary, subcommand discoverability, device-flow auth, JSON output for piping, streaming chat by default. Strategic value: every VMG owner already running `claude` Pro or `gh auth login` will reach for `agentprovision` next. Distribution surface = product surface.

## Goal

Ship a single-binary CLI that lets a tenant operator run, inspect, and orchestrate AgentProvision from the terminal. Distributed via Homebrew + `cargo install`. Built on a shared Rust core extracted from Luna's `src-tauri/`.

## Deliverables

### 1. `apps/agentprovision-core/` — new shared Rust crate

The business logic that both Luna (Tauri GUI) and the CLI need. Extracted from Luna's current `src-tauri/src/api.rs`, `auth.rs`, etc. so neither surface duplicates code.

Modules:
- `auth` — token storage (OS keychain via `keyring` crate), device-flow login, refresh
- `client` — `reqwest`-based API client; handles base URL, auth header, error model
- `models` — serde structs matching API schemas (Tenant, Agent, Workflow, ChatMessage, etc.)
- `chat` — streaming chat helper (SSE consumer)
- `events` — `/chat/sessions/{id}/events/stream` SSE consumer for tail-events
- `mcp` — MCP-tool client for `agentprovision tool call` (rare power-user surface)
- `config` — read/write `~/.config/agentprovision/config.toml` (server URL, default tenant, default agent, aliases)

### 2. `apps/agentprovision-cli/` — new CLI crate

Built on `clap` (derive API) for subcommand structure + `dialoguer` for interactive prompts + `console`/`indicatif` for color/progress + `termimad` for streaming markdown rendering of chat replies.

Top-level subcommands:

```
agentprovision login                            # device-flow OAuth → keychain
agentprovision logout
agentprovision status                           # current user, tenant, server, version

agentprovision chat                             # interactive REPL → default agent (streams)
agentprovision chat send <prompt> [--agent X]
agentprovision chat history [--session ID]
agentprovision chat tail                        # follow chat events SSE

agentprovision agent ls
agentprovision agent show <slug>
agentprovision agent run <slug> --prompt <text>

agentprovision workflow ls
agentprovision workflow run <name> [--input KEY=VAL ...]
agentprovision workflow status <run-id>
agentprovision workflow tail <run-id>           # follow run via /workflows/runs/{id}/events

agentprovision integration ls
agentprovision integration show <name>
agentprovision integration test <name>          # /integrations/{id}/test endpoint

agentprovision memory recall <query>            # /memory/recall — returns top-K observations
agentprovision memory observe <text> --entity <name>

agentprovision skill ls
agentprovision skill show <name>

agentprovision tenant ls                        # if user is in multiple tenants
agentprovision tenant switch <name>             # rewrite default in config

agentprovision config get <key>
agentprovision config set <key> <value>
agentprovision config alias add <name> <expansion>     # llm-style aliases

agentprovision tool call <mcp-tool> [--arg KEY=VAL]    # power-user direct MCP invocation
```

Global flags:
- `--json` — emit machine-readable JSON for any command (the gh CLI gold standard)
- `--server URL` — override server (defaults to `agentprovision.com`)
- `--tenant ID` — override default tenant for this invocation
- `--no-stream` — wait for full response, don't stream
- `--output FILE` — write to file instead of stdout (chat / workflow runs)
- `-v / -vv` — verbose / debug logs to stderr

### 3. Distribution

- **Homebrew tap** — `brew install agentprovision/tap/agentprovision`. Auto-update via `brew upgrade`.
- **`cargo install agentprovision`** — for Rust devs who already have a toolchain.
- **GitHub Releases** — pre-built binaries per OS (mac-arm64, mac-x64, linux-x64, win-x64). The Tauri release workflow already builds Mac ARM; adapt for the CLI binary.
- **Optional npm wrapper** — `npm install -g @agentprovision/cli` downloads the right binary at install time. Convenient for JS-heavy customers but not required for v1.
- **Auto-updater** — same pattern as `gh`: `agentprovision upgrade` checks GitHub Releases.

### 4. Documentation

- `apps/agentprovision-cli/README.md` with quickstart (login → chat → first workflow run)
- A man page (auto-generated from clap)
- Inline `agentprovision help <subcommand>` (clap default)

### 5. PR pipeline

This will be a multi-PR effort because of the core extraction:
- PR-A: extract `agentprovision-core` from Luna's `src-tauri/`. Luna keeps building, no behavior change.
- PR-B: scaffold `agentprovision-cli` skeleton with login + chat + status. Useful baseline.
- PR-C: add agent / workflow / integration / memory / skill subcommands.
- PR-D: distribution — Homebrew tap, GitHub Releases workflow.

Each branch off `feat/agentprovision-cli-core`, `feat/agentprovision-cli-skeleton`, etc.

## Scope — IN

- Single static binary (Rust + clap)
- Same-tenant operations (login, chat, workflow, memory, integration)
- Streaming chat with markdown rendering (termimad)
- `--json` output mode for every command
- OS-keychain token storage (mac Keychain via `keyring` crate)
- Subcommand discovery + auto-generated man page
- Aliases (llm-style)
- Plugin surface — defer to v2; but keep the architecture hospitable (clap allows external subcommands à la `git foo` resolving `git-foo` on PATH)

## Scope — OUT (v1)

- Multi-tenant simultaneous operations (CLI is single-tenant per invocation; switch via `tenant switch`)
- Cron-like scheduling from the CLI itself (the platform has Dynamic Workflows for that)
- Full MCP server lifecycle management (`agentprovision tool` is a thin invoke, not a manage surface)
- TUI dashboard (ratatui-style) — defer
- Native Windows installer — provide MSI in v2; for v1 just `scoop install` works

## Architecture notes

### Why Rust over Go / Python

- Luna's `src-tauri/` is already Rust; extraction means we ship the same code in two surfaces with zero rework
- Single static binary, fast cold start (~30ms vs Python's ~250ms for `llm`)
- Strong type safety on the API client (serde structs are the spec)
- `gh`'s success in Go proves a CLI can win this market with strong UX; Rust's clap is feature-equivalent to Cobra

### Why not just a Tauri app entry point

Tauri's `wry` (webview) layer pulls ~40MB of dependencies and a slow startup. CLIs need <100ms cold start. Sharing the **business logic** (`agentprovision-core`) but keeping the **frontend** (Tauri vs. clap) separate is the clean factoring.

### Auth flow (device-code, gh-style)

```
$ agentprovision login
! First copy your one-time code: ABCD-1234
- Press Enter to open agentprovision.com/login/device in your browser...
✓ Authentication complete.
✓ Logged in as Simon Aguilera (saguilera1608@gmail.com), tenant AgentProvision (752626d9).
✓ Token saved to macOS Keychain.
```

Backend support: a `/api/v1/auth/device-code` endpoint that mints + polls. Modeled on GitHub's device-flow.

## Steps

1. **PR-A — extract core (week 1):**
   - Move `apps/luna-client/src-tauri/src/api.rs` (and friends) into `apps/agentprovision-core/`
   - Update Luna's `Cargo.toml` to depend on the new crate
   - All Luna tests still green; no behavior change
2. **PR-B — CLI skeleton (week 1):**
   - `cargo new --bin apps/agentprovision-cli`
   - Implement: `login`, `logout`, `status`, `chat send`, `chat (REPL)`
   - `--json` global flag
   - Smoke test: end-to-end against the live api
3. **PR-C — subcommand expansion (week 2):**
   - `agent`, `workflow`, `integration`, `memory`, `skill`, `tenant`, `config`
4. **PR-D — distribution (week 2-3):**
   - GitHub Releases workflow that builds per-OS binaries
   - Homebrew tap repo (`nomad3/homebrew-tap`) with `agentprovision.rb` formula
   - `agentprovision upgrade` self-update command
   - Auto-generated man page

## Definition of Done

- ✅ `agentprovision-core` crate extracted; Luna depends on it; Luna tests + Tauri build still green
- ✅ `agentprovision-cli` binary builds and ships login + chat (interactive + send) + every key subcommand listed above
- ✅ `--json` flag works on every command that returns structured data
- ✅ Token stored in OS keychain, not plain text
- ✅ Streaming chat reply renders markdown nicely (code blocks, headers, lists)
- ✅ Homebrew tap published; `brew install agentprovision/tap/agentprovision` works
- ✅ GitHub Releases publishes mac-arm64, mac-x64, linux-x64 binaries on every tag
- ✅ Man page + `--help` for every subcommand
- ✅ All PRs assigned to nomad3, no AI credit lines

## Risks

- Core extraction touches Luna; if the Tauri-side API surface diverges from current usage, regressions surface in the GUI. Test coverage on Luna's chat path is the safety net.
- Device-flow auth requires a backend endpoint that doesn't exist yet — small backend API change in PR-A or alongside PR-B.
- Homebrew tap requires a separate GitHub repo (`nomad3/homebrew-tap`); first-time setup. Documented but it's a manual one-time step.
- npm wrapper sometimes triggers AV false-positives on Windows (binary downloads); defer to v2.

## Cross-references

- Luna client: `apps/luna-client/src-tauri/` (source of the Rust code we're extracting)
- Memory: `feedback_use_pipeline.md` — never build Tauri locally; Homebrew + GitHub Releases are CI-driven, no laptop builds
- Reference UX: `gh` (cli/cli on GitHub), `llm` (simonw/llm), Higgs Field CLI

## Why this matters strategically

A CLI is the canonical consumption surface for the developer half of the VMG/operator market. It's also the cleanest way to demonstrate orchestration — `agentprovision workflow run multi-site-revenue-sync --watch` is what Simon shows in the VMG demo, not a GIF of a web UI. And every Pulse partner-program reference (Otto, Chckvet) ships a CLI; not having one is a soft gap.
