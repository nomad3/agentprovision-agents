# Luna computer-use — core-feature productionization (design v2)

**Status:** v2 — Codex (gpt-5.5) review folded in; pending Luna review + operator sign-off · **Date:** 2026-06-09 · **Owner:** nomade

**Directive (Simon, 2026-06-09):** Luna macOS computer-use is a **core feature for all tenants**, not a per-operator-machine rig. The actuation config must be *maintained* as production config — durable across deploys, multi-tenant, drift-free across compose/Helm/Terraform.

**Decisions locked with the operator:** per-tenant signing keys from day one; full productionization now.

**Review state:** v1 reviewed by Codex gpt-5.5 (companion file `…-codex-review.md`, verdict *sound-with-changes*, 5 blockers). All findings folded into this v2 — see §11. Builds on shipped Phase 3 (pointer) + Phase 4 (keyboard); see `docs/operator/luna-e2e/` + memory `luna_computer_use_e2e_complete`.

---

## 1. Current state (map + Codex verification)

**Tenant-scoped already:** `desktop_commands`, `desktop_command_approval_grants`, `desktop_command_events`, `desktop_command_envelope_nonces` (all carry `tenant_id`), and `luna_presence_service._presence_store` (keyed by tenant).

**Gaps (Codex-verified):**

| # | Gap | Severity | Note |
|---|---|---|---|
| G1 | Global Ed25519 **private key absent from Helm externalSecret** → legacy global-key path fails-late on K8s. **But** the per-tenant design needs only `ENCRYPTION_KEY`, which **is** already wired (api + worker). So this matters only for the *legacy global-key fallback* during cutover. | high | I2 corrected |
| G2 | orchestration-worker has 4 `DESKTOP_*` knobs in compose, **zero in Helm** | blocker | confirmed |
| G3 | **Zero per-tenant gating** — no `tenant_features` desktop column | blocker | confirmed |
| G4 | Single **global bundle allowlist**, not per-tenant, never served to client | high | confirmed |
| G5 | Client reads enablement + keys **only at launch (env/`option_env!`)**; no server path | high | confirmed |
| G6 | **No runtime public-key distribution** → rotation = hard cutover | high | confirmed |
| G7 | `JWT_AGENT_TOKEN_SECRET` falls back to `SECRET_KEY`; not in any secret store | medium | confirmed |
| G8 | ~~Keyboard hard-disabled~~ — **STALE**: `_DISABLED_NATIVE_CONTROL_ACTIONS` is empty since #844; keyboard is enabled fleet-wide. Real gap: keyboard has **no per-tenant gate** | medium | I1 corrected |
| G9 | **Terraform has zero** desktop config; also AWS/K8s provider vs Helm's GCP Secret Manager — **source-of-truth mismatch** | medium | I4 |
| **G10** | **Claim-time enforcement gap** — gating only grant/enqueue/observation leaves the real boundary (`claim_next_desktop_command` + completion verify) ungated; a queued command actuates after a kill-switch flip | **blocker** | B1 |
| **G11** | **Rotation needs `key_id`-aware verify** — Ed25519 verify ignores `key_id`, verifies vs the global key | **blocker** | B4 |
| **G12** | **Client boundary doesn't bind `tenant_id`/`user_id`** from the envelope | **blocker** | B5 |
| **G13** | **Client config delivery layer** — Rust has no authed HTTP client; React owns auth/presence/claims | **blocker** | B3 |
| **G14** | MCP exposes only *observation* desktop tools, not pointer/keyboard command tools | medium | I7 — scoped OUT (see §2) |

---

## 2. Goals / non-goals

**Goals:** per-tenant enablement (fail-closed kill-switch, default OFF, ramped, operator first); per-tenant Ed25519 keys with no-downtime rotation, private keys never leaving the server; server-driven client delivery of flags + public-key registry + effective allowlist; durable drift-free config across compose/Helm/Terraform with fail-fast on misconfig; **cutover that never breaks the operator's currently-live canary** (B2).

**Non-goals (this rollout):** Phase 5 free-text→actuation; **MCP pointer/keyboard command tools** (G14 — the productionization targets the *API-native command path* the canary already uses; adding an MCP actuation surface is a separate, deliberately-gated effort); Windows/Linux; changing the proven boundary/lease/bounds *logic* (only its config + gating + tenant-binding).

---

## 3. Design decisions (resolved)

| Fork | Decision | Rationale |
|---|---|---|
| Signing key scope | **Per-tenant keypairs**, versioned `key_id`, rotation overlap | A compromised tenant key can't forge another tenant's envelopes. |
| Per-tenant key storage | **New `desktop_command_signing_keys` table; private key Fernet-encrypted via existing `ENCRYPTION_KEY`** — a *dedicated* signing-key service, **not** `IntegrationCredential` CRUD reuse (I2) | Scales to all tenants, no new per-tenant secret seeding; only managed secret stays `ENCRYPTION_KEY` (already wired). |
| Client delivery | **React (`api.js`/`apiFetch`) fetches `/presence/capabilities`, passes flags+keys into Rust via a Tauri command** (B3); env/`option_env` only as offline fail-closed fallback | Rust has no authed HTTP client; React already owns auth/presence/claims. |
| Target allowlist | **Per-tenant JSONB**; effective = `tenant ∩ platform floor` | Per-tenant canary; floor blocks tenant-admin self-grant of un-blessed bundles. |
| Rollout | **Per-tenant flag ramp**, default OFF, operator first, **with operator-tenant backfill in the enforcement deploy** (B2) | House pattern; cutover must not break the live canary. |
| Validation | **Fail-fast at readiness via a dedicated cached preflight** (global crypto + active-enabled tenants only — not a per-request DB sweep, I5); claim-time check kept as defense-in-depth | Misconfig surfaces at deploy, cheaply. |

---

## 4. Architecture

### 4.1 `tenant_features` additions (migration, `red_flag_engine_enabled` precedent — Bool `NOT NULL default false server_default false`)
`desktop_control_enabled` (master kill-switch), `native_control_enabled` (pointer), `keyboard_control_enabled` (keyboard — replaces the now-empty static disabled-set as the gate), `native_control_target_allowlist` (JSONB `default '[]'`).

### 4.2 Per-tenant signing-key registry (new table + `desktop_signing_key_service`)
`desktop_command_signing_keys`: `id`, `tenant_id` (FK, idx), `key_id` (unique per tenant), `algorithm`, `public_key` (b64url), `private_key_encrypted` (Fernet via `ENCRYPTION_KEY`; never served/logged), `status` (`active`|`retiring`|`retired`), timestamps. Partial unique index = one `active` per tenant.
- **Dedicated service** (not vault CRUD): `generate_for_tenant` (Ed25519 keygen + Fernet-encrypt private + insert active, idempotent), `rotate_for_tenant`, `resolve_signing_key(tenant_id)`, `resolve_verify_keys(tenant_id)` → {active + retiring}.
- **Sign AND verify resolve by `(tenant_id, key_id)`** (B4/G11): the envelope's `key_id` selects the verify key; accept `active` + `retiring`, **reject unknown/retired**. Envelope `key_id` becomes the tenant's `key_id`. Global env `DESKTOP_COMMAND_ENVELOPE_ED25519_*` remains a **legacy fallback key_id** accepted during cutover only.

### 4.3 Enforcement hook points (server) — including the real boundary (B1/G10)
Read the caller's `tenant_features` and re-check at **every** transition, fail-closed:
- `create_desktop_approval_grant` (`:1913`) → 403 if `not desktop_control_enabled`.
- `enqueue_desktop_command` (`:2074`) → 403; route pointer via `native_control_enabled`, keyboard via `keyboard_control_enabled`.
- `record_mcp_observation_request` (`:1997`) / `record_local_observation_event` (`:1849`) → deny if disabled.
- **`claim_next_desktop_command` (`:2202`/`:2282`) + completion verify (`:1519`)** → re-check tenant flag + effective allowlist + `(tenant_id,key_id)` at claim/approval-match/completion; **deny pending fail-closed when policy is now off** (B1).
- `_native_control_target_is_allowlisted(tenant_id, bundle)` (`:903`) → effective = per-tenant JSONB `∩` global env floor.

### 4.4 Capabilities endpoint (extend `app/api/v1/presence.py`)
`GET /api/v1/presence/capabilities` (tenant from auth) → `{desktop_control_enabled, native_control_enabled, keyboard_control_enabled, envelope_signing_algorithm, allowed_bundle_ids, active_key_id, public_keys{key_id→b64url}, expires_at}`. No private material.

### 4.5 Client consumption (B3/B5/I6)
- **React** fetches `/presence/capabilities` via `apiFetch` (auth'd) at startup + refresh; caches with **`expires_at`**; **clears on logout/tenant-switch/401/network-fail and disables control on stale/failed refresh** (I6). Passes flags + key registry into Rust through a **Tauri command** (Rust has no authed HTTP client).
- Rust drives pointer/keyboard enablement + the verify-key registry from that injected config; `LUNA_ACTUATION_*`/`option_env` kept only as offline fail-closed fallback.
- **Boundary binds identity (B5/G12):** the native proof path validates the envelope's `tenant_id`/`user_id` against the expected session tenant/user (carried JS→Rust) and requires exact match before actuation.
- Ships signed DMG via CI (never build Tauri manually).

### 4.6 Validation + durability parity
- **Dedicated cached readiness preflight** (I5): validates `ENCRYPTION_KEY` present + active tenant keys decrypt for *enabled* tenants; not a per-request `/api/v1` sweep. Claim-time check retained as defense-in-depth.
- **Parity:** add the global Ed25519 private key (legacy fallback) + **`JWT_AGENT_TOKEN_SECRET` as a distinct secret** (I3) to api + worker externalSecrets; mirror the non-secret `DESKTOP_*` knobs into worker Helm + compose + **local Helm + `.env.example`** (N1). **Resolve the secret source-of-truth first** (Helm=GCP Secret Manager vs Terraform=AWS/K8s, I4/G9) before writing TF.
- **Redaction (N3):** add `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY`, `JWT_AGENT_TOKEN_SECRET`, signing-key encrypted fields to the redaction set before any logging work. Fix stale comments (N2).

---

## 5. Security model
Per-tenant key isolation (own key signs envelopes; `(tenant_id,key_id)`-resolved verify, reject unknown/retired — B4); private keys Fernet at rest, never served/logged; rotation overlap (active+retiring) = no-downtime; identity binding (envelope `tenant_id`/`user_id` matched client-side — B5); fail-closed everywhere (default OFF, empty effective allowlist denies, missing/!decryptable key fails readiness + denies at claim, stale client cache disables control); granular per-tenant kill-switch re-checked at the claim boundary (B1).

## 6. Rollout + cutover (B2)
Migration default OFF ⇒ zero behavior change for the fleet. **The operator's canary tenant must not break:** the enforcement deploy (PR4) **backfills the operator tenant** (`desktop_control_enabled`/`native_control_enabled`=true + allowlist) and seeds its per-tenant active key, while verify keeps **accepting the legacy global `key_id`** until the client picks up the per-tenant key via capabilities (overlap). Then ramp other tenants; `keyboard_control_enabled` follows pointer once stable. Operator runbook (`docs/operator/`): pre-deploy checklist (ENCRYPTION_KEY + JWT secret seeded, worker parity, capabilities reachable, preflight green) + rotation runbook.

## 7. PR plan (chained; Codex gpt-5.5 + Luna review each; assigned nomade; no secrets committed)
1. **PR1** — this design doc (+ Codex review folded; Luna review next).
2. **PR2** — durability/de-drift, no behavior change: `JWT_AGENT_TOKEN_SECRET` (distinct) + legacy Ed25519 key to api+worker externalSecrets; mirror non-secret knobs to worker Helm + compose + local + `.env.example`; **decide secret source-of-truth** then TF. Redaction-set additions. (G1/G2/G7/G9/N1/N3)
3. **PR3** — dedicated cached readiness preflight (I5/G… ); claim-time check retained.
4. **PR4** — per-tenant schema + enforcement at **all** hook points incl. claim/completion (B1) + keyboard via flag (I1) + per-tenant allowlist (G3/G4) **+ operator-tenant backfill** (B2). Default OFF ⇒ no fleet change; operator stays enabled.
5. **PR5** — per-tenant key registry + dedicated service + `(tenant_id,key_id)` sign/verify accepting active+retiring+legacy-during-overlap + rotation (B4/G11/I2).
6. **PR6** — `/presence/capabilities` endpoint (G6) with `expires_at`.
7. **PR7** — client: React `apiFetch` → Tauri-command injection; cache fail-closed (I6); identity binding in boundary (B5); offline fallback (B3/G5/G12). Signed DMG via CI.
8. **PR8** — ramp + runbook + extend `computer-use-suite.sh` (flag OFF ⇒ 403/deny; per-tenant key verify; rotation overlap).

## 8. Testing
API pytest per gate (incl. claim/completion fail-closed), key generate/rotate/`(tenant,key_id)` verify round-trip, capabilities shape, preflight; Rust unit tests for capabilities parse + key selection + identity binding + offline fallback; E2E extends the suite (OFF⇒deny, per-tenant verify, rotation overlap). CI's isolated Postgres only — never prod DB.

## 9. Open items (resolved by review)
- Secret **source-of-truth** (Helm GCP SM vs TF AWS/K8s) — reconcile in PR2 *before* TF (I4).
- Worker-signs-envelopes? — worker parity is required regardless for config-load correctness; verify the exact signing call sites in PR2.
- MCP pointer/keyboard tools (G14/I7) — **out of scope**; this rollout targets the API-native command path.

## 10. Risks
Eager key-gen on enablement (one row; revisit if deploy latency); client offline-first stays disabled unless baked dev key matches (fail-closed, confirm UX); HMAC transitional path deprecated once all-Ed25519 (G7); strict migration order PR4→PR5→PR6→PR7.

## 11. Codex (gpt-5.5) review v1 — findings & resolutions
Full review: companion `…-codex-review.md`. Resolutions in this v2: **B1**→§4.3 claim/completion enforcement (G10); **B2**→§6 operator backfill + legacy-key overlap; **B3**→§4.5 React+Tauri layering (G13); **B4**→§4.2 `(tenant,key_id)` sign/verify (G11); **B5**→§4.5 identity binding (G12); **I1**→G8 reframed; **I2**→§4.2 dedicated service + ENCRYPTION_KEY-wired note; **I3**→§4.6 distinct JWT secret; **I4**→§4.6/§9 secret source-of-truth first; **I5**→§4.6 cached preflight; **I6**→§4.5 cache fail-closed; **I7**→§2 scoped out; **N1**→§4.6 local parity; **N2**→§4.6 comment cleanup; **N3**→§4.6 redaction. **Next:** Luna review of this v2, then operator sign-off, then PR2.
