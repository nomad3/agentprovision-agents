# alpha

`alpha` — the AgentProvision CLI. Single-binary client for the AgentProvision platform: login, chat, run workflows, and orchestrate agents (Claude Code / Codex / Gemini CLI / GitHub Copilot CLI) from your terminal.

The CLI is the orchestrator-of-CLIs: every command you run flows through the agentprovision.com control plane, which dispatches to the right runtime (Temporal workflows, MCP tool calls, A2A coalitions) under the hood.

Plan: [`docs/plans/2026-05-09-agentprovision-cli-design.md`](../../docs/plans/2026-05-09-agentprovision-cli-design.md).

## Install

```bash
# macOS
curl -fsSL https://agentprovision.com/install.sh | sh

# Windows (PowerShell)
iwr -useb https://agentprovision.com/install.ps1 | iex
```

No sudo. No admin. Drops `alpha` in `~/.local/bin/` (POSIX) or `%USERPROFILE%\.agentprovision\bin\` (Windows). Linux musl + Windows ARM64 cross-compile ship in PR-D-1.5.

For Rust devs:

```bash
cargo install agentprovision-cli  # installs the `alpha` binary onto PATH
```

## Quick start

```bash
# Login (device-flow first, falls back to email/password if backend doesn't support it)
alpha login

# In CI / scripts
AGENTPROVISION_PASSWORD=... alpha login \
    --password --email me@example.com --password-env AGENTPROVISION_PASSWORD

# Confirm
alpha status
alpha --json status

# One-shot chat
alpha chat send "what's the status of yesterday's lead pipeline?"

# Streaming chat (default)
alpha chat send "summarise the Levi's MDM incident in 3 bullets"

# Non-streaming
alpha --no-stream chat send "..."

# Interactive REPL
alpha chat repl
```

## Build from source

```bash
cd apps/agentprovision-cli
cargo build --release
./target/release/alpha --help
```

## Global flags

| Flag | Description | Env var |
|------|-------------|---------|
| `--server URL` | Override API base URL | `AGENTPROVISION_SERVER` |
| `--json` | Emit JSON instead of pretty output | — |
| `--no-stream` | Wait for full chat reply | — |
| `-v` / `-vv` | Verbose / debug stderr logs | — |

## Token storage

Tokens land in the OS keychain (macOS Keychain / Linux secret-service / Windows Credential Manager) under service `agentprovision`. The account string is the host portion of the API URL so prod and self-hosted tokens stay separate.

`alpha logout` removes the entry.

## Configuration

`~/.config/agentprovision/config.toml` (XDG-respecting). Honoured today: `server`, `tenant_id`. PR-C exposes `config get / set / alias`.

## Architecture

`alpha` is a thin shell around [`agentprovision-core`](../agentprovision-core/), the same Rust crate Luna's Tauri client links against. Auth, API client, models, and SSE consumers live there; the CLI only adds the clap surface, terminal output, and the REPL loop.

## Versioning

`cli-v*` git tags trigger the release workflow (`.github/workflows/cli-release.yaml`). Tag version must match `apps/agentprovision-cli/Cargo.toml` `version=` — the validate job fails the build on drift.

Crate name is `agentprovision-cli` (for crates.io); binary name is `alpha` (for `$PATH`).
