# Schema freeze handoff → Claudia B (Alpha CLI/core typed models)

Typed-model contract for desktop-control so Alpha CLI/core can mirror every Luna-facing API/event
shape (plan constraint: API+CLI parity in the same slice). Verified read-only against code
2026-06-07. Each model lists API + Tauri source anchors so both sides stay in lockstep.
**FROZEN** = do not change without a schema version bump + council review. **PROVISIONAL** = still
moving; type defensively / leave additive room.

---

## 1. Persisted models — FROZEN

### `desktop_commands` — `apps/api/app/models/desktop_command.py:13-54`
```
id(uuid PK), tenant_id, user_id?, session_id, shell_id(str96), device_id?(fk device_registry),
approval_id?(uuid), correlation_id(uuid), capability(str64), status(str32),
source(str32, default "api"), nonce?(str96), payload(JSONB),
lease_owner_shell_id?(str96), lease_expires_at?, claimed_at?, completed_at?, created_at, updated_at
```
`status` enum: `pending | claimed | running | succeeded | failed | denied | preempted | expired`.
No `seq_no` column (sequence numbers PROVISIONAL). Pending TTL = `created_at` + 300s
(`DEFAULT_COMMAND_PENDING_TTL_SECONDS`); lease default 30s (`DEFAULT_COMMAND_LEASE_SECONDS`).

### `desktop_command_events` — `desktop_command_event.py:13-48` (append-only audit)
```
id, tenant_id, user_id?, session_id, desktop_command_id, approval_id?, correlation_id?,
event_type(str64), source(str32), action(str64), capability(str64), outcome(str32),
reason?(str512), mode?(str32), shell_id(str96), device_id?, event_metadata(JSONB), created_at
```
**Gotcha for B:** ORM attribute is `event_metadata` but the DB column is `"metadata"`.
`source` ∈ `{mcp, local_user, api, tauri, tauri_local}`. `outcome` ∈
`{requested, approved, started, succeeded, failed, denied, stopped, preempted, expired}`.
`event_metadata` keys are restricted to the 16-key allowlist (see `02`).

### `desktop_command_approval_grants` — `desktop_command_approval_grant.py:13-75`
```
id, tenant_id, user_id?, session_id, shell_id(str96), device_id?, desktop_command_id?,
risk_tier(str32), capability(str64), status(str32, default "active"), target_binding(JSONB),
max_actions(int), remaining_actions(int), approved_by_user_id?, approved_at, expires_at,
consumed_at?, revoked_at?, created_at, updated_at
```
`risk_tier` ∈ `{observe, native_control}`; `status` ∈ `{active, consumed, revoked, expired}`.
Consumption = atomic CAS in the claim txn (12-predicate WHERE). Unique partial index: one active
command-bound grant per `(tenant_id, desktop_command_id)` (migration 162).
**Note:** `target_binding` currently enforces only the `action` key on claim; `bundle_id` /
`window_title_pattern` are accepted but not yet enforced (P2 follow-up — type the field, don't rely on enforcement yet).

### `desktop_command_envelope_nonces` — `desktop_command_envelope_nonce.py:13-52`
```
id, tenant_id, desktop_command_id, session_id, shell_id(str96), device_id?, nonce(str96),
envelope_hash(str64), status(str32, default "issued"), issued_at, expires_at, consumed_at?, created_at, updated_at
```
`status` ∈ `{issued, consumed, replayed, expired}`. Unique `(tenant_id, nonce)`. Single-use
consumption is a CAS at completion. No cleanup job yet (P2).

---

## 2. On-the-wire command envelope `agentprovision.desktop_command_envelope.v1` — FROZEN shape
API issuer `_build_signed_command_envelope` (`desktop_control_service.py:1136-1164`);
Tauri `NativeControlBoundaryEnvelope` (`lib.rs` ~386). Fields:
```
schema, signed(true), signature_alg, key_id, policy_version(1), issuer("agentprovision-api"),
tenant_id, user_id, session_id, desktop_command_id, correlation_id?, shell_id, device_id?,
action, tool_name, capability, mode, risk_tier, approval_id?, approval_risk_tier,
policy_decision, nonce, issued_at(ISO), expires_at(ISO), expires_at_ms(int), signature
```
Tauri envelope additionally carries `revoked`, `replayed` (bool). Two algorithms share the shape:
- **HMAC-SHA256** (`key_id = agentprovision-desktop-command-hmac-v1`) — default; used for the
  observe command claim→complete path; verified server-side at completion.
- **Ed25519** (`signature_alg = "Ed25519"`) — required for native-boundary *proof* requests;
  verified client-side (`lib.rs:820-859`, real `VerifyingKey::verify`) **and** still terminates
  `tier_enabled=false` before any actuation.
Canonical signing JSON = sorted keys, `signature` removed, control-char/`del` escaped
(`canonical_envelope_payload_json`). Keep both sides byte-identical or signatures break.

## 3. Ed25519 key registry — PROVISIONAL
Config knobs:
- API: `DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID` (selects issuance key id).
- Tauri/client: `LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEYS` (registry,
  `key_id=public_key` separated by comma/semicolon/newline) with fallback
  `LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY`; default key id
  `agentprovision-desktop-command-ed25519-v1`. Key material decodes base64url:/hex:/plain.
Fail-closed errors: `envelope key unknown`, `envelope key registry invalid`,
`envelope public key invalid`, `envelope signature invalid`.
**Still pending (do not hard-type as stable):** key generation, secure per-device storage in
`device_registry`, rotation epochs, revocation polling, TTL-bound-into-policy, per-device
monotonic sequence numbers, durable Tauri-side replay window. (Plan Next Actions #6; this is your design lane.)

## 4. Read-only state/result contracts — FROZEN (mirror display-safe; see `02`)
- **ObservationResult**: `{ result_kind ∈ {binary,string,json,error,unsupported,unknown},
  result_size_bytes | result_size_chars, result_fields ⊂ {app,title_present,title_chars} }`.
- **DesktopPermissionReadiness** (`permissions.rs:21-30`): `app_identity` + 6 `PermissionProbe`
  (`screen_recording, accessibility, automation_system_events, input_monitoring, camera, microphone`).
  `PermissionProbe = { status ∈ {granted,denied,not_required,unknown}, required_for[], reason }`.
  `PermissionAppIdentity = { bundle_id?, executable_path?, app_bundle_path?,
  code_signature_identifier?, code_signature_team_identifier?, code_signature_kind?, permission_scope_note }`.
  *Reserved additive:* `why_needed` may later move server-side (currently client copy in
  `ControlSafetyStrip.jsx`) — leave room, don't require it.
- **ControlSafetyState** (`lib.rs` ~280): `{ mode ∈ {control_locked,observe,stopped},
  observe_enabled, assist_enabled, control_enabled, stopped, control_locked, capture_running,
  gesture_state, cursor_global, can_observe, can_assist, can_control,
  can_control_pointer(false), can_control_keyboard(false), alpha_kernel{...},
  macos_app_monitor{...}, permissions, last_stop_at_ms }`.
- **macos_app_monitor_event.v1**: see `02` §5.

---

## 5. API routes B must mirror in Alpha CLI/core (prefix `/api/v1/desktop-control`)
| Method · Path | Auth | Rate | Purpose |
|---|---|---|---|
| POST `/events/local-observation` | user JWT | 240/min | Tauri local observation audit ingestion |
| POST `/internal/observations/request` | internal-key + `X-Tenant-Id` + `X-User-Id` | 120/min | MCP observation request (denial-only today) |
| POST `/internal/approval-grants` | internal-key | 120/min | approval grant creation |
| POST `/internal/commands` | internal-key | 120/min | command enqueue |
| POST `/commands/claim` | desktop device token | 240/min | claim lease (CAS + approval consume + envelope issue) |
| POST `/commands/{command_id}/complete` | desktop device token | 240/min | complete (envelope + nonce verify) |
| POST `/commands/stop` | device token / user | 120/min | Stop → preempt + revoke grants |
Source: `apps/api/app/api/v1/desktop_control.py:342-528`.

## 6. Tauri command surface (`lib.rs:2374-2389`) — for the kernel adapter
`alpha_kernel_status, get_or_create_shell_id, control_get_safety_state,
control_prove_native_command_boundary, control_observe_status, control_stop_all, control_lock_all,
control_clear_stop, control_open_permission_setup, capture_screenshot, get_active_app,
read_clipboard, control_pointer_move, control_pointer_click, control_keyboard_type,
control_keyboard_key_chord` (last 4 = denial stubs; never actuate).

## 7. Display-safe denial / reason taxonomy — FROZEN prefixes (type as a closed enum of CLI errors)
```
desktop control stopped; <action> denied|preempted
desktop observe locked; <action> denied
desktop native control disabled
desktop native control tier disabled
desktop command envelope key unknown | signature invalid | public key invalid
  | key registry invalid | binding mismatch | expired | replayed
replay denied
lease expired
approval missing | revoked | expired | exhausted | binding_mismatch
down-channel unavailable | shell cannot observe
No connected desktop shell   (HTTP 409)
```
Alpha CLI must surface these display-safe (never raw screen/clipboard content) in its error models.

---

## 8. Migration ledger
Desktop-control migrations occupy **158–162** (confirmed: `159_chat_sessions_owner_user_id`,
`160` command-nonce tenant-scoped index, `161_desktop_command_envelope_nonces`,
`162_desktop_command_approval_grants`). **Next available = 163.** Re-confirm at apply time:
`ls apps/api/migrations/*.sql | sort | tail -1`, then `git add -f`, then insert into `_migrations`
(column is `filename`).

## 9. FROZEN vs PROVISIONAL — quick map
| Item | State |
|---|---|
| 4 persisted models (§1), event/result enums, 16-key metadata allowlist, mirror fields | FROZEN |
| Envelope v1 field set (§2), canonical signing JSON | FROZEN |
| Routes (§5), Tauri command surface (§6), denial taxonomy (§7) | FROZEN |
| Permission readiness / ControlSafetyState / monitor v1 shapes | FROZEN |
| Ed25519 key lifecycle, seq numbers, TTL-in-policy, Tauri durable replay, observe-path approval consumption, `why_needed` server field | PROVISIONAL |
