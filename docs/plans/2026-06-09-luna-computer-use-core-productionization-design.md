# Luna computer-use — core-feature productionization (design v3)

**Status:** v3 — Codex gpt-5.5 (codebase) + Luna (platform) reviews folded in; pending operator sign-off · **Date:** 2026-06-09 · **Owner:** nomade

**Directive (Simon):** Luna macOS computer-use is a **core feature for all tenants** — meaning *available to every tenant behind default-off enablement*, NOT fleet-wide activation (Luna L-I6). Config must be *maintained* production config: durable across deploys, multi-tenant, drift-free across compose/Helm/Terraform, and expressed through the **Alpha CLI kernel**.

**Decisions:** per-tenant signing keys from day one; full productionization now.

**Reviews folded:** Codex gpt-5.5 (companion `…-codex-review.md`, *sound-with-changes*, 5 blockers — §11). Luna platform review (companion `…-luna-review.md`, *sound direction, not platform-approved until kernel surface + governance added* — §12). This v3 addresses both.

Builds on shipped Phase 3 (pointer) + Phase 4 (keyboard); see `docs/operator/luna-e2e/`, memory `luna_computer_use_e2e_complete`.

---

## 1. Current state (map + reviews)

Tenant-scoped today: `desktop_commands`, `desktop_command_approval_grants`, `desktop_command_events`, `desktop_command_envelope_nonces`, `luna_presence_service._presence_store`. Gaps (severity after both reviews):

| # | Gap | Sev |
|---|---|---|
| G1 | Global Ed25519 key absent from Helm externalSecret (legacy-fallback only; per-tenant path needs just `ENCRYPTION_KEY`, already wired) | high |
| G2 | orchestration-worker: 4 `DESKTOP_*` in compose, **zero in Helm** | blocker |
| G3 | **Zero per-tenant gating** | blocker |
| G4 | Global allowlist, not per-tenant, not served | high |
| G5 | Client reads enablement+keys only at launch (env/`option_env`) | high |
| G6 | No runtime public-key distribution → rotation = hard cutover | high |
| G7 | `JWT_AGENT_TOKEN_SECRET` falls back to `SECRET_KEY`, not in secret store | medium |
| G8 | ~~keyboard hard-disabled~~ STALE (#844) → real gap = no per-tenant keyboard gate | medium |
| G9 | Terraform zero + AWS/K8s vs Helm-GCP **secret source-of-truth mismatch** | medium |
| G10 | **Claim-time enforcement gap** (the real boundary is `claim_next_desktop_command` + completion) | blocker (Codex B1) |
| G11 | **Rotation needs `(tenant_id,key_id)`-aware verify** | blocker (Codex B4) |
| G12 | **Client boundary doesn't bind `tenant_id`/`user_id`** | blocker (Codex B5) |
| G13 | **Client delivery layer** — Rust has no auth'd HTTP; React owns it | blocker (Codex B3) |
| G14 | MCP exposes only observation tools (scoped OUT — §2) | medium |
| **G15** | **No Alpha CLI kernel surface** — routes/services don't delegate to `alpha desktop` verbs | **blocker (Luna L-B1)** |
| **G16** | **Agent governance under-specified** for the API-native actuation path (tool-group split, agent-token/JWT scope) | **blocker (Luna L-B2)** |
| **G17** | Event/RL wiring unplaced; capabilities not a thin projection; admin-only mutability; single-SSE; value-arbitration/safety-floor; rollout-as-enablement | important (Luna L-I1…I6) |

---

## 2. Goals / non-goals

**Goals:** per-tenant enablement (fail-closed, default OFF, ramped, operator first) expressed through `alpha desktop` verbs with thin v1 routes; per-tenant Ed25519 keys with no-downtime rotation; server-driven client delivery; agent-governance boundary (tool-group + scope) on the API-native path; value/safety-floor in approval admission; durable drift-free config; cutover that never breaks the operator's live canary.

**Non-goals:** Phase 5 free-text→actuation; **MCP pointer/keyboard command tools** (G14 — *and any future MCP actuation MUST wrap the same `alpha desktop` verbs + tool-group scopes*, Luna L-N4); Windows/Linux; changing the proven boundary/lease/bounds *logic*.

---

## 3. Design decisions (resolved)

Per-tenant keypairs (versioned `key_id`, rotation overlap); per-tenant key storage = **new `desktop_command_signing_keys` table, private key Fernet via existing `ENCRYPTION_KEY`, dedicated service** (not `IntegrationCredential` reuse — Codex I2); client delivery = **React `apiFetch` → Tauri command into Rust** (Codex B3); per-tenant JSONB allowlist, effective = `tenant ∩ platform floor`; per-tenant flag ramp, default OFF, operator first **with enforcement-deploy backfill** (Codex B2); fail-fast readiness via **dedicated cached preflight** (Codex I5). All surfaced as `alpha desktop` verbs (Luna L-B1).

## 4. Architecture

### 4.0 Alpha CLI kernel surface (Luna L-B1 / G15) — *the spine; everything else delegates here*
New kernel verbs in the `alpha` CLI, each a thin v1 HTTP route delegating to one shared Python service entrypoint (no business logic in the route):
- `alpha desktop capabilities get` → `GET /api/v1/presence/capabilities`
- `alpha desktop enablement get|set` → tenant flags (superuser/operator-only — §4.1)
- `alpha desktop keys generate|rotate|list` → per-tenant key registry (§4.2)
- `alpha desktop allowlist get|set` → per-tenant target allowlist
- `alpha desktop preflight run` → readiness validation (§4.6)
- `alpha desktop commands audit|list` → operator inspection (NOT actuation issuance)

`publish_session_event` + `rl_experience` emitted from the shared service layer so every viewport (CLI, web, leaf-via-MCP) gets identical behavior.

### 4.1 `tenant_features` additions (Bool `NOT NULL default false server_default false`; **superuser/operator-only mutability**, excluded from member-writable updates, allowlist changes audited — Luna L-I3)
`desktop_control_enabled` (master kill-switch — **also gates observation**, Luna L-N2), `pointer_control_enabled` (renamed from `native_control_enabled` — Luna L-N1), `keyboard_control_enabled`, `native_control_target_allowlist` (JSONB `default '[]'`). (Optionally a distinct `desktop_observe_enabled` if observation must ramp separately from the master switch.)

### 4.2 Per-tenant signing-key registry (`desktop_command_signing_keys` + `desktop_signing_key_service`)
Columns: `id`, `tenant_id`(FK,idx), `key_id`(unique per tenant), `algorithm`, `public_key`(b64url), `private_key_encrypted`(Fernet via `ENCRYPTION_KEY`; never served/logged), `status`(active|retiring|retired), timestamps. Partial-unique = one active/tenant. Service: `generate_for_tenant`, `rotate_for_tenant`, `resolve_signing_key`, `resolve_verify_keys`(active+retiring). **Sign AND verify resolve by `(tenant_id, key_id)`** (Codex B4/G11); accept active+retiring, reject unknown/retired; legacy global `key_id` accepted during cutover only. Surfaced via `alpha desktop keys`.

### 4.3 Enforcement + governance (Codex B1/G10, Luna L-B2/G16, L-I5)
- **Agent-governance boundary** (L-B2): split the desktop tool surface into `desktop_observe` vs `desktop_control` tool-groups; enforce agent-token scope + user/JWT permission at every desktop entrypoint; align the MCP observe-tool scope. The tenant flag is necessary but **not** the sole boundary.
- **Tenant + scope gating at every transition, fail-closed:** `create_desktop_approval_grant`, `enqueue_desktop_command` (pointer via `pointer_control_enabled`, keyboard via `keyboard_control_enabled`), `record_mcp_observation_request`/`record_local_observation_event`, **and `claim_next_desktop_command` + completion verify** (Codex B1) — re-check flag + scope + effective allowlist + `(tenant,key_id)`; deny pending fail-closed when policy flips off.
- **Approval admission carries a value/safety verdict** (L-I5): safety-floor veto, tenant norms, substrate throttling, audit outcome — or an explicit documented reason the desktop policy layer is the sole arbitration boundary for this phase.
- `_native_control_target_is_allowlisted(tenant_id, bundle)` → effective = per-tenant `∩` global floor.

### 4.4 Capabilities (thin projection of `alpha desktop capabilities get` — Luna L-I2)
`GET /api/v1/presence/capabilities` returns `{policy_version, generated_at, desktop_control_enabled, pointer_control_enabled, keyboard_control_enabled, envelope_signing_algorithm, allowed_bundle_ids, active_key_id, public_keys{key_id→b64url}, expires_at, disabled_reason_codes}`. No private material; a thin read of the same service the verb calls.

### 4.5 Client consumption (Codex B3/B5/I6, Luna L-I4)
React `apiFetch`es `/presence/capabilities` at startup + refresh; caches with `expires_at`; **clears on logout/tenant-switch/401/network-fail, disables control on stale/failed refresh** (Codex I6); passes flags + key registry into Rust via a Tauri command. Rust drives enablement + the `(key_id)` verify registry from that; env/`option_env` only as offline fail-closed fallback. **Boundary binds the envelope's `tenant_id`/`user_id` against the expected session identity** (Codex B5). **Command/session events flow through the one shared per-session SSE provider — no per-component desktop streams** (Luna L-I4). Signed DMG via CI.

### 4.6 Validation + durability parity + observability
Dedicated cached readiness preflight (`alpha desktop preflight run`): `ENCRYPTION_KEY` present + active keys decrypt for *enabled* tenants — not a per-request sweep (Codex I5); claim-time check retained. Parity: legacy Ed25519 key + **distinct `JWT_AGENT_TOKEN_SECRET`** (Codex I3) into api+worker externalSecrets; non-secret knobs into worker Helm + compose + **local Helm + `.env.example`** (Codex N1); **reconcile secret source-of-truth** (Helm-GCP vs TF-AWS/K8s, Codex I4) before TF. Redaction-set: `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY`, `JWT_AGENT_TOKEN_SECRET`, signing-key fields (Codex N3); fix stale comments (N2). **Platform metrics** (Luna L-N3): enabled tenants, active enrolled devices, deny reasons, stale-capability disables, key-rotation success/fail, command deny/complete counts.

## 5. Security model
Per-tenant key isolation ((tenant,key_id)-resolved verify, reject unknown/retired); Fernet at rest, never served/logged; rotation overlap = no-downtime; identity binding (envelope tenant/user matched client-side); agent-governance boundary (tool-group + token scope + JWT perms) on top of the tenant flag; value/safety-floor in approval admission; fail-closed everywhere (default OFF, empty allowlist denies, missing/!decryptable key fails preflight + denies at claim, stale client cache disables); granular kill-switch re-checked at the claim boundary.

## 6. Rollout + cutover
"Available to every tenant behind **default-off enablement**", not fleet-wide (Luna L-I6). First-class UX gates: tenant-admin enablement, per-device enrollment, TCC readiness, visible mode, Stop, revocation. Migration default OFF ⇒ zero fleet change. **Operator canary preserved:** the enforcement deploy backfills the operator tenant's flags + active key and verify keeps accepting the legacy global `key_id` until the client picks up the per-tenant key (overlap). Then ramp; keyboard after pointer is stable. Operator runbook (`docs/operator/`): pre-deploy checklist + rotation runbook.

## 7. PR plan (chained; Codex gpt-5.5 + Luna review each; assigned nomade; no secrets committed)
1. **PR1** — design doc (+ both reviews folded; this v3).
2. **PR2** — durability/de-drift, no behavior change (secrets→externalSecrets, worker/compose/local parity, redaction, source-of-truth then TF). G1/G2/G7/G9.
3. **PR3** — dedicated cached readiness preflight + `alpha desktop preflight run`.
4. **PR4** — `tenant_features` schema (admin-only) + enforcement at **all** hook points incl. claim/completion + **agent-governance tool-group split + scope** (L-B2) + keyboard-via-flag + per-tenant allowlist + **operator backfill**. Default OFF ⇒ no fleet change.
5. **PR5** — per-tenant key registry + service + `(tenant,key_id)` sign/verify + rotation + `alpha desktop keys`.
6. **PR6** — `/presence/capabilities` + `alpha desktop capabilities get` (thin projection, policy_version, reason codes) + `publish_session_event`/`rl_experience` placement (L-I1).
7. **PR7** — client: React `apiFetch`→Tauri injection, cache fail-closed, identity binding, single-SSE adherence, offline fallback. Signed DMG via CI.
8. **PR8** — `alpha desktop enablement/allowlist/commands` verbs + ramp + runbook + metrics + extend `computer-use-suite.sh` (OFF⇒deny, per-tenant verify, rotation overlap, scope deny).

## 8. Testing
API pytest per gate (incl. claim/completion + scope fail-closed), key generate/rotate/(tenant,key_id) verify, capabilities/verb projection, preflight, value/safety-floor admission; Rust tests for capabilities parse + key selection + identity binding + offline fallback + single-SSE; E2E extends the suite. CI isolated Postgres only.

## 9. Open items
Secret source-of-truth (Helm-GCP vs TF-AWS/K8s) reconciled in PR2 before TF; worker signing call-sites verified in PR2; `desktop_observe_enabled` as a distinct flag vs master-gated (decide in PR4); MCP actuation out of scope but must wrap `alpha desktop` verbs when built.

## 10. Risks
Eager key-gen on enablement; client offline-first stays disabled (fail-closed); HMAC transitional path deprecated once all-Ed25519; strict migration order PR4→PR5→PR6→PR7; the agent-governance tool-group split must not regress the existing observation tools.

## 11. Codex (gpt-5.5) review v1 — folded
B1→§4.3 claim/completion; B2→§6 backfill+overlap; B3→§4.5 React+Tauri; B4→§4.2 (tenant,key_id); B5→§4.5 identity binding; I1→G8 reframed; I2→§4.2 dedicated service; I3→§4.6 distinct JWT secret; I4→§4.6/§9 source-of-truth; I5→§4.6 cached preflight; I6→§4.5 cache fail-closed; I7→§2 scoped out; N1/N2/N3→§4.6.

## 12. Luna (platform) review v2 — folded
L-B1→§4.0 Alpha CLI kernel verbs + thin routes; L-B2→§4.3 agent-governance tool-group split + scope; L-I1→§4.0/§4.6/PR6 event+RL placement; L-I2→§4.4 thin projection + policy_version/reason codes; L-I3→§4.1 admin-only mutability + allowlist audit; L-I4→§4.5 single-SSE; L-I5→§4.3 value/safety-floor admission; L-I6→§6 rollout-as-enablement + UX gates; L-N1→§4.1 rename pointer_control_enabled; L-N2→§4.1 observe gating; L-N3→§4.6 metrics; L-N4→§2 future-MCP wraps verbs. **Next:** operator sign-off, then PR2.
