# Luna server-side pointer-command issuance (Phase 3 server dependency)

Date: 2026-06-08
Status: implementing
Plan parent: `docs/plans/2026-06-07-luna-macos-app-control-plan.md` (Phase 3)

## Why

The Luna client Phase 3 pointer canary (merged #839) actuates only when it
receives a **server-signed pointer envelope** via the prove→actuate flow. But
the API deliberately refuses to issue native-control commands:
`_enqueue_disabled_native_control_command` in
`apps/api/app/services/desktop_control_service.py` returns `status="denied"`,
`native_control.enabled=False`, reason "signed envelopes and approval grants
required". So the production flow can't complete end to end.

User chose (2026-06-08) the real production path: build server issuance, not a
client-side test-signed canary.

## What already exists (reuse, do not rebuild)

- `_build_signed_command_envelope` already fully signs native-control envelopes:
  risk_tier, capability, approval_id, target binding (from the approval grant),
  ed25519/HMAC signature. Used at **claim** time.
- `claim_next_desktop_command` already consumes an approval grant
  (`_consume_approval_grant_or_deny` / `_matching_approval_grant`: tenant, user,
  session, shell, device, risk_tier, capability, active, budget>0, not expired,
  target allowlisted + `_native_control_targets_match`) and signs the envelope.
- Target binding helpers: `_normalize_native_control_target_binding`,
  `_native_control_target_is_allowlisted` (gated on
  `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`), `_require_native_control_target_binding`.
- Signing config: `DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM` (Ed25519),
  `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY`,
  `DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID`
  (`agentprovision-desktop-command-ed25519-v1` = the client's default key_id).

So the ONLY gap is the **enqueue** routing: pointer actions go to the deny stub
instead of producing a pending native-control command.

## Change

1. Split `_DISABLED_NATIVE_CONTROL_ACTIONS`: keep **keyboard** actions disabled
   (Phase 4); add `_POINTER_CONTROL_ACTIONS = {pointer_move, pointer_click}`.
2. New `_enqueue_native_control_command(...)` modelled on the observe enqueue:
   - Require the connected shell (same `_select_connected_shell`).
   - Require `request.approval_id` (native control must reference a grant).
   - Extract the target from `request.payload["target"]`, normalize +
     allowlist-validate via `_require_native_control_target_binding` (422 if not
     allowlisted) — so we never enqueue a command that must fail at claim.
   - Create a `pending` command: capability=pointer_control,
     mode="control_locked", payload={action, tool_name, mode, target,
     request metadata, approval_id}, nonce, approval_id. Idempotent on nonce like
     the observe path.
   - Record `desktop_command_queued` + publish a display-safe session event.
3. Route pointer actions to it in `enqueue_desktop_command`; keyboard stays on
   `_enqueue_disabled_native_control_command`.

Keyboard remains fully disabled (Phase 4). The claim path is unchanged — it
already signs + consumes the grant.

## Tests (SQLite test fixture, isolated — safe locally)

- pointer enqueue with valid approval grant + allowlisted target → `pending`
  (not denied), payload carries the normalized target.
- pointer enqueue with a non-allowlisted target → 422.
- pointer enqueue missing approval_id → denied/422 (native control needs a grant).
- keyboard enqueue → still `denied` via the disabled path.
- full claim of a pending pointer command → signed envelope with
  capability=pointer_control, risk_tier=native_control, target present,
  signature verifies with the ed25519 public key; approval grant consumed.

## E2E config (separate step, on the installed app)

- API: `DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM=Ed25519`,
  `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY=<32-byte b64url>`,
  `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST=<safe target bundle id>`.
- Client: `LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY=<matching public key>`,
  `LUNA_ACTUATION_POINTER_ENABLED=true`.
- Flow: create approval grant → enqueue pointer_move → client claims → proves →
  actuates real cursor against the safe target; verify Stop preemption.

## Review

Codex is currently down (operator note). Implemented with self-review +
comprehensive tests; external Codex/Luna review pending availability.
