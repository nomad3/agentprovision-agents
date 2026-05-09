# agentprovision-core

Shared Rust business logic for the AgentProvision platform. Consumed by:

- **`apps/luna-client/src-tauri/`** — Luna desktop / mobile client (Tauri 2)
- **`apps/agentprovision-cli/`** — `agentprovision` command-line tool

The crate is GUI-agnostic. It provides:

| Module    | Purpose |
|-----------|---------|
| `client`  | `reqwest`-based async API client with bearer-token auth |
| `auth`    | Token storage trait (`MemoryTokenStore`, `KeyringTokenStore` behind the `keyring` feature) + email/password login + device-flow login |
| `models`  | Serde structs for `Tenant`, `Agent`, `ChatSession`, `Workflow`, ... |
| `chat`    | Streaming chat helper (Server-Sent Events) |
| `events`  | Session-event SSE consumer (`/chat/sessions/{id}/events/stream`) |
| `mcp`     | Minimal MCP-tool client |
| `config`  | `~/.config/agentprovision/config.toml` reader/writer |
| `error`   | Unified `Error` / `Result` types |

## Features

- **`keyring`** — Pull in the OS-keychain backend (macOS Keychain, Linux secret-service, Windows Credential Manager). Off by default; the CLI enables it.

## Why a shared crate?

The plan in `docs/plans/2026-05-09-agentprovision-cli-design.md` calls out duplication risk: Luna's Rust side and the new CLI both need an API client, auth, and SSE consumer. Keeping them in one crate means the CLI ships exactly the same bytes Luna does for the client / auth / config layers — no drift, one place to fix bugs, one place to add new endpoints.

## Backend dependencies

The device-flow login (`auth::request_device_code` / `auth::poll_device_token`) hits:

- `POST /api/v1/auth/device-code` — mints user_code + device_code
- `POST /api/v1/auth/device-token` — polls for approval
- `POST /api/v1/auth/device-approve` — called by the web UI when the user enters the code

These endpoints land alongside the core crate as part of PR-A. If the backend is older than that, callers should fall back to `auth::login_password`.
