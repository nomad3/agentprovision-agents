# Codex (gpt-5.5) review — computer-use productionization design (v1)

Read-only adversarial review of `2026-06-09-luna-computer-use-core-productionization-design.md`, run via `codex exec -m gpt-5.5 -s read-only` against the live codebase on 2026-06-09. **Verdict: sound-with-changes.** Gap check: G1–G7 + G9 confirmed; **G8 stale** (keyboard already enabled, `_DISABLED_NATIVE_CONTROL_ACTIONS` is empty since #844).

## Blockers
- **B1 — claim-time enforcement missed.** The real actuation boundary is `claim_next_desktop_command` (`desktop_control_service.py:2202/2282`) + completion verify (`:1519`), not just grant/enqueue/observation. A queued command can still actuate after a tenant kill-switch flips. Fix: re-check tenant feature + effective allowlist at claim, approval-match, and completion; deny pending fail-closed when policy is now off.
- **B2 — PR order breaks the operator's live canary.** No tenant desktop flag exists today; live behavior depends on global signing/allowlist. Default-off enforcement before the operator tenant is seeded denies the working canary (`tenant_features.py:63`, `desktop_control_service.py:844/1280`). Fix: backfill the operator tenant's flags + active key in the same deploy as enforcement, and keep a scoped legacy global-key fallback until cutover.
- **B3 — client delivery targets the wrong layer.** Rust has an env/build-time key registry and no HTTP/auth client; React owns authed API + presence + claims (`lib.rs:722/1310`, `api.js:20`, `useDesktopCommandClaims.js:824`). Fix: fetch `/presence/capabilities` in React via `apiFetch`, pass flags/keys into Rust via a Tauri command.
- **B4 — rotation not implementable with current verify.** Ed25519 verify ignores `key_id`, verifies against the global key (`desktop_control_service.py:1351/1395`). Fix: sign/verify resolve by `(tenant_id, key_id)`; accept active + retiring; reject unknown/retired.
- **B5 — boundary doesn't bind tenant/user client-side.** Envelopes carry `tenant_id`/`user_id` but JS/Rust don't validate them (`desktop_control_service.py:1398`, `useDesktopCommandClaims.js:205`, `lib.rs:416/1035`). Fix: carry expected tenant/user into the boundary check, require exact match.

## Important
- **I1** G8 stale → reframe as "add per-tenant gates for pointer + keyboard" (`desktop_control_service.py:100`).
- **I2** `ENCRYPTION_KEY` already wired in API + worker Helm (`config.py:117`, `credential_vault.py:22`, `agentprovision-api.yaml:192`, `agentprovision-orchestration-worker.yaml:91`). Reuse the Fernet helper but build a **separate** signing-key table/service — do NOT reuse `IntegrationCredential` CRUD.
- **I3** `JWT_AGENT_TOKEN_SECRET` not separately wired, falls back to `SECRET_KEY` (`config.py:196`, `desktop_control_service.py:1260`). Add a distinct secret before relying on HMAC fallback.
- **I4** Terraform here is AWS/Kubernetes; Helm references a GCP Secret Manager ExternalSecret (`main.tf:1`, `agentprovision-api.yaml:164`). Define the real secret source-of-truth first, then matching TF provider/resources.
- **I5** Readiness fail-fast must be a dedicated cached preflight (global crypto + active-enabled tenants), not a per-request `/api/v1` DB/key sweep (`agentprovision-api.yaml:69`, `routes.py:124`).
- **I6** Capability cache needs explicit fail-closed: `expires_at`, clear on auth/tenant change, disable on stale/401/network-fail (`lib.rs:1310`, `api.js:20`).
- **I7** MCP exposes only observation desktop tools, not pointer/keyboard command tools (`desktop_control.py:24`, `tool_groups.py:228`). Scope the doc to the API-native command path, or add the MCP surface deliberately with the same gates.

## Nits
- **N1** Local Helm + `.env.example` parity missing from the plan (`agentprovision-api-local.yaml:75`, `agentprovision-orchestration-worker-local.yaml:55`, `.env.example:31`).
- **N2** Misleading stale comments (`desktop_control_service.py:712`, `desktop_control.py:3`).
- **N3** Add to redaction before logging work: `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY`, `JWT_AGENT_TOKEN_SECRET`, signing-key encrypted fields (`skill_manager.py:176`).
