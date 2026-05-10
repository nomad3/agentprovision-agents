# agentprovision

Single-binary CLI for the AgentProvision platform — login, chat, run workflows, and orchestrate agents from your terminal.

This crate is the **PR-B skeleton**: `login`, `logout`, `status`, `chat send`, and an interactive `chat repl`. PR-C extends this with `agent`, `workflow`, `integration`, `memory`, `skill`, `tenant`, `config`, and `tool` subcommands. PR-D adds Homebrew + GitHub Releases distribution.

Plan: [`docs/plans/2026-05-09-agentprovision-cli-design.md`](../../docs/plans/2026-05-09-agentprovision-cli-design.md).

## Quick start

```bash
# Build
cd apps/agentprovision-cli
cargo build --release

# Login (device-flow first, falls back to email/password if backend doesn't support it)
./target/release/agentprovision login

# Or in CI / scripts
AGENTPROVISION_PASSWORD=... ./target/release/agentprovision login \
    --password --email me@example.com --password-env AGENTPROVISION_PASSWORD

# Confirm
./target/release/agentprovision status
./target/release/agentprovision --json status

# One-shot chat
./target/release/agentprovision chat send "what's the status of yesterday's lead pipeline?"

# Streaming chat (default)
./target/release/agentprovision chat send "summarise the Levi's MDM incident in 3 bullets"

# Non-streaming
./target/release/agentprovision --no-stream chat send "..."

# Interactive REPL
./target/release/agentprovision chat repl
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

`agentprovision logout` removes the entry.

## Configuration

`~/.config/agentprovision/config.toml` (XDG-respecting). Honoured today: `server`, `tenant_id`. PR-C exposes `config get / set / alias`.

## Architecture

The CLI is a thin shell around [`agentprovision-core`](../agentprovision-core/), the same Rust crate Luna's Tauri client links against. Auth, API client, models, and SSE consumers live there; the CLI only adds the clap surface, terminal output, and the REPL loop.
