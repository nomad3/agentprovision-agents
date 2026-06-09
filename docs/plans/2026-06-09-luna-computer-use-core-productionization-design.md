# Luna computer-use — core-feature productionization (design)

**Status:** Draft for Codex (gpt-5.5) + Luna review · **Date:** 2026-06-09 · **Owner:** nomade

**Directive (Simon, 2026-06-09):** Luna macOS computer-use is a **core feature for all tenants**, not a per-operator-machine rig. The actuation config must be *maintained* as production config — durable across deploys, multi-tenant, drift-free across compose/Helm/Terraform.

**Decisions locked with the operator (this turn):**
- **Per-tenant signing keys from day one** (not one shared platform key).
- **Full productionization now** (durability + per-tenant gating + key rotation + server-driven client delivery), not a phased subset.

Builds on the shipped Phase 3 (pointer) + Phase 4 (keyboard) actuation — see `docs/operator/luna-e2e/` and the memory `luna_computer_use_e2e_complete`.

---

## 1. Current state (from the 5-layer config map)

**Tenant-scoped already:** `desktop_commands`, `desktop_command_approval_grants`, `desktop_command_events`, `desktop_command_envelope_nonces` (all carry `tenant_id`), and `luna_presence_service._presence_store` (keyed by tenant).

**Global / hardcoded — the productionization gaps:**

| # | Gap | Severity | Evidence |
|---|---|---|---|
| G1 | Ed25519 **private key absent from the Helm externalSecret** → K8s deploy comes up Ready then denies every native command at first claim (`RuntimeError: ...ED25519_PRIVATE_KEY is required`). Fail-late. | blocker | `helm/values/agentprovision-api.yaml` externalSecret has SECRET_KEY/DATABASE_URL/ENCRYPTION_KEY/… but no desktop key; consumed at `desktop_control_service.py` claim path |
| G2 | **orchestration-worker** has all 4 `DESKTOP_*` knobs in compose, **zero in Helm** | blocker | `docker-compose.yml` worker env vs empty `helm/values/agentprovision-orchestration-worker.yaml` |
| G3 | **Zero per-tenant gating** — native control is cluster-wide env only; no `tenant_features` flag | blocker | `tenant_features.py` has no desktop column; pattern exists for `value_layer_enabled`, `nightly_reflection_enabled`, `red_flag_engine_enabled`, `enforce_strict_tool_scope` |
| G4 | Single **global bundle allowlist**, not per-tenant, never served to the client | high | `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` (`config.py`, `desktop_control_service.py:_native_control_target_is_allowlisted`) |
| G5 | Client reads enablement + verification keys **only at launch (env / `option_env!`)** — no server-driven path; rotation/per-tenant ⇒ re-env or DMG rebuild | high | `lib.rs` `LUNA_ACTUATION_*`, `LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY(S)`; build bakes only `VITE_API_BASE_URL` |
| G6 | **No runtime public-key distribution** → rotation = hard cutover with client breakage | high | server embeds `key_id` but exposes no key-registry endpoint |
| G7 | `JWT_AGENT_TOKEN_SECRET` silently falls back to `SECRET_KEY` for HMAC envelopes; not in any secret store | medium | `_desktop_command_envelope_secret()` returns `JWT_AGENT_TOKEN_SECRET or SECRET_KEY` |
| G8 | Phase 4 keyboard **hard-disabled in code** (`_DISABLED_NATIVE_CONTROL_ACTIONS`), not flag-gated | medium | `desktop_control_service.py` constant |
| G9 | **Terraform has zero** desktop-control config or key resource | medium | `infra/terraform` grep empty; violates no-drift rule |

---

## 2. Goals / non-goals

**Goals**
- Per-tenant enablement with a fail-closed master kill-switch, default OFF, ramped per tenant (operator's tenant first).
- Per-tenant Ed25519 signing keys with no-downtime rotation; private keys never leave the server.
- Server-driven client delivery of enablement flags + public-key registry + effective allowlist.
- Durable, drift-free config across docker-compose / Helm / Terraform; fail-fast on misconfig.

**Non-goals (this rollout)**
- Phase 5 free-text→actuation (Luna interpreting "move the mouse" itself). Unchanged: actuation is driven by server-issued signed commands.
- Windows/Linux clients. macOS only.
- Changing the proven boundary/lease/bounds actuation logic — only its *configuration & gating* surface.

---

## 3. Design decisions (resolved)

| Fork | Decision | Rationale |
|---|---|---|
| Signing key scope | **Per-tenant keypairs**, versioned `key_id`, rotation overlap window | Operator choice. A compromised tenant key cannot forge another tenant's envelopes. |
| Per-tenant key storage | **DB table, private key Fernet-encrypted via existing `ENCRYPTION_KEY`** (credential-vault pattern) — NOT per-tenant Secret Manager entries | Scales to all tenants with **no new per-tenant secret seeding**; the only managed secret stays `ENCRYPTION_KEY`, already in the secret store + helm. Sidesteps G1/G9's per-tenant-seeding problem. |
| Client config delivery | **Server-driven** `GET /api/v1/presence/capabilities`; env/`option_env` kept only as offline fail-closed fallback | One signed DMG for the fleet; rotation/enablement is operator-controlled at runtime. |
| Target allowlist | **Per-tenant JSONB** on `tenant_features`; effective = `tenant_allowlist ∩ platform_floor` (global env) | Per-tenant canary; platform floor prevents a tenant-admin self-granting an un-blessed bundle. Per-grant `target_binding` unchanged underneath. |
| Rollout | **Per-tenant flag ramp**, default OFF, operator's tenant first | House pattern for every risky feature; highest-blast-radius capability needs kill-switch granularity. |
| Envelope-config validation | **Fail-fast at readiness** (gated to the per-tenant-key path), claim-time check kept as defense-in-depth | Misconfig surfaces at deploy, not at first user command. |

---

## 4. Architecture

### 4.1 `tenant_features` additions (migration, `red_flag_engine_enabled` precedent — Boolean `NOT NULL default false server_default false`)

- `desktop_control_enabled` (Bool) — **master kill-switch** (gates observation + grants + commands).
- `native_control_enabled` (Bool) — Phase 3 pointer actuation.
- `keyboard_control_enabled` (Bool) — Phase 4 keyboard actuation (replaces the static `_DISABLED_NATIVE_CONTROL_ACTIONS` gate, G8).
- `native_control_target_allowlist` (JSONB `default '[]'`) — per-tenant bundle allowlist (G4).

Master/sub semantics: a sub-capability is effective only if `desktop_control_enabled AND <sub>` and the tenant has an active signing key.

### 4.2 Per-tenant signing-key registry (new table `desktop_command_signing_keys`, migration)

| column | notes |
|---|---|
| `id` uuid pk | |
| `tenant_id` FK, indexed | per-tenant |
| `key_id` text | e.g. `tnt-<short>-ed25519-v1`; unique per tenant; embedded in envelopes |
| `algorithm` text | `Ed25519` |
| `public_key` text | base64url; served to client |
| `private_key_encrypted` text | **Fernet via `ENCRYPTION_KEY`** (credential-vault helper); never served, never logged |
| `status` text | `active` \| `retiring` \| `retired` |
| `created_at`, `activated_at`, `retiring_at`, `retired_at` | |

- **Partial unique index:** one `active` key per tenant.
- **Generation** (`desktop_signing_key_service.generate_for_tenant`): on enablement (or lazily on first sign), generate an Ed25519 keypair (`cryptography`), Fernet-encrypt the private key, insert `active`. Idempotent.
- **Signing:** `_desktop_command_envelope_*` resolves the *calling tenant's* active key (decrypt private via Fernet), signs, sets envelope `key_id` to the tenant's `key_id`. The global env `DESKTOP_COMMAND_ENVELOPE_ED25519_*` becomes a **bootstrap/legacy fallback** only.
- **Rotation** (`rotate_for_tenant`): generate new `active`, mark old `retiring` (still advertised + accepted for verification through a grace window), then `retired`. No downtime; client verifies against whichever advertised `key_id` matches the envelope.

> This makes G1 (private key not in Helm secret) and G9 (no per-tenant TF seeding) largely **dissolve**: the only secret is `ENCRYPTION_KEY`, already in the externalSecret + compose + (to-be-added) Terraform. Per-tenant private keys live in Postgres (durable PVC), encrypted at rest.

### 4.3 Enforcement hook points (server)

Gate at the four sites the map identified, reading the caller's `tenant_features`:
- `create_desktop_approval_grant` → 403 if `not desktop_control_enabled`.
- `enqueue_desktop_command` → 403 if `not desktop_control_enabled`; route pointer via `native_control_enabled`, keyboard via `keyboard_control_enabled` (replacing the static disabled-set).
- `record_mcp_observation_request` / `record_local_observation_event` → deny if `not desktop_control_enabled` (per-tenant observation kill-switch).
- `_native_control_target_is_allowlisted(tenant_id, bundle)` → effective allowlist = per-tenant JSONB `∩` global env floor.

### 4.4 Capabilities endpoint (extend `app/api/v1/presence.py`)

`GET /api/v1/presence/capabilities` (tenant resolved from the caller's auth) →
```json
{
  "desktop_control_enabled": true,
  "native_control_enabled": true,
  "keyboard_control_enabled": false,
  "envelope_signing_algorithm": "Ed25519",
  "allowed_bundle_ids": ["com.apple.Terminal"],
  "active_key_id": "tnt-ab12-ed25519-v1",
  "public_keys": { "tnt-ab12-ed25519-v1": "<b64url>", "tnt-ab12-ed25519-v0": "<b64url during rotation>" }
}
```
No private material. Internal variant under `/internal/*` for service callers if needed.

### 4.5 Luna client consumption (`lib.rs`)

- Fetch `/presence/capabilities` at startup + on a refresh interval; cache it.
- Drive pointer/keyboard enablement and the verification key registry from the response (the client already has a multi-key registry lookup — extend it to load from the API).
- `LUNA_ACTUATION_*` / `option_env!` public keys retained **only** as an offline fail-closed fallback (no network at launch ⇒ stay disabled unless a baked dev key matches).
- Ships on a signed DMG via CI (never build Tauri manually).

### 4.6 Fail-fast validation + durability parity

- Promote `_validate_desktop_command_envelope_signing_config()` to a **readiness pre-flight** gated to the signing path: verify `ENCRYPTION_KEY` present and that an active tenant key decrypts (smoke). Missing config fails the deploy, not the first command. Keep claim-time check as defense-in-depth.
- **Parity:** `ENCRYPTION_KEY` in api + orchestration-worker externalSecret (G1/G2); mirror the 3 non-secret `DESKTOP_*` knobs (algorithm default, global key_id, platform allowlist floor) into worker Helm + `docker-compose`; add Terraform variables + secret-manager resource for `ENCRYPTION_KEY` (value out-of-band) and the non-secret knobs (G9). Add `JWT_AGENT_TOKEN_SECRET` to both externalSecrets (G7) for the transitional HMAC path.

---

## 5. Security model

- **Per-tenant isolation:** envelopes signed with the tenant's own key; cross-tenant forgery requires that tenant's private key. Private keys Fernet-encrypted at rest; never served, never logged (add to the log-redaction set).
- **Rotation:** overlap window (active + retiring both advertised/accepted) ⇒ no-downtime rotation, operator-triggered.
- **Fail-closed everywhere:** default OFF; empty effective allowlist ⇒ deny; missing/!decryptable key ⇒ readiness fail (deploy) + claim deny (runtime). Platform floor caps tenant-admin allowlist.
- **Blast radius:** a misbehaving tenant client is disabled by flipping its `desktop_control_enabled` — granular kill-switch, no fleet-wide flip.

---

## 6. Rollout

Default OFF for all tenants (migration server_default false ⇒ zero behavior change on deploy). Ramp: flip `desktop_control_enabled` + `native_control_enabled` for the operator's canary tenant → watch RL/auto-scores + `desktop_command_events` → widen. `keyboard_control_enabled` ramps only after pointer is stable fleet-wide. Operator runbook (`docs/operator/`) with a pre-deploy checklist (ENCRYPTION_KEY seeded, worker parity, capabilities reachable, fail-fast green).

---

## 7. PR plan (chained off the prior branch where files overlap; each reviewed via Codex gpt-5.5 + Luna; assigned to nomade; no secrets committed)

1. **PR1 — this design doc** + Codex/Luna review sign-off.
2. **PR2 — durability/de-drift, no behavior change:** add `ENCRYPTION_KEY` + `JWT_AGENT_TOKEN_SECRET` to api + orchestration-worker externalSecrets; mirror the 3 non-secret `DESKTOP_*` knobs into worker Helm + compose; Terraform variables + secret-manager resource. (Closes G1/G2/G7/G9 at the infra layer.)
3. **PR3 — fail-fast validation:** readiness pre-flight for the signing path; smoke test that a misconfigured signing deploy fails readiness; claim-time check retained.
4. **PR4 — per-tenant schema + enforcement:** migration (4 `tenant_features` columns, `#631` server_default playbook) + enforcement at the 4 hook points + keyboard routed via flag (closes G3/G4/G8). Default OFF ⇒ no behavior change.
5. **PR5 — per-tenant key registry + rotation:** `desktop_command_signing_keys` table + `desktop_signing_key_service` (generate/rotate, Fernet) + per-tenant signing in the envelope path + rotation overlap (closes the per-tenant-key core).
6. **PR6 — capabilities endpoint:** `GET /presence/capabilities` resolved from `tenant_features` + key registry (closes G6 server side).
7. **PR7 — Luna client consumes capabilities:** server-driven enablement + key registry; env/`option_env` fallback only; ships signed DMG via CI (closes G5).
8. **PR8 — ramp + runbook:** flip operator's tenant, observe, widen; `docs/operator/` pre-deploy checklist + rotation runbook; extend `docs/operator/luna-e2e/computer-use-suite.sh` with a per-tenant-gating assertion (flag OFF ⇒ 403/deny).

---

## 8. Testing

- API: pytest for each hook-point gate (OFF⇒deny, ON⇒allow), key generate/rotate/verify round-trip, capabilities payload shape, fail-fast readiness. Run against CI's isolated Postgres (never prod DB).
- Client: Rust unit tests for capabilities parse + key-registry selection + offline fallback; existing boundary/lease/bounds tests unchanged.
- E2E: extend `computer-use-suite.sh` — flag OFF ⇒ 403/deny; per-tenant key envelope verifies; rotation overlap (old+new both verify) — run live on the operator's tenant.

## 9. Risks & open questions

- **Key generation cost / lazy vs eager:** generate eagerly on enablement (simpler, one extra row) — proposed; revisit if it adds deploy latency.
- **Client offline-first launch:** with no network, client stays disabled unless a baked dev key matches — acceptable (fail-closed); confirm UX copy.
- **HMAC transitional path:** keep until all tenants are Ed25519, then deprecate `JWT_AGENT_TOKEN_SECRET` fallback (G7) — tracked, not blocking.
- **Migration ordering:** `tenant_features` columns (PR4) before key registry (PR5) before capabilities (PR6) before client (PR7) — strict order.
- **Open:** does any existing Temporal workflow sign envelopes from the orchestration-worker today, or only the API? (Affects whether PR2 worker parity is load-bearing now or just future-proofing — verify before PR2.)

## 10. Review

Per the standing process: this doc is reviewed by **Codex (gpt-5.5)** and **Luna** before any implementation; findings folded in; then operator sign-off; then PR2 begins.
