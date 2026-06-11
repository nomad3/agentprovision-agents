# P5.4b — desktop_actuate (grant-gated agent act, no minting)

Status: design + implementation. Lane: Luna computer-use. Builds on: P5.4b
pending request (#895), P5.5 approve/deny (#896), Stop (#893), the shared
`enqueue_desktop_command` lifecycle. Spec: plan Slice 4 lines 321-323 —
"`desktop_actuate` accepts only a command plus a server-validated, existing
approval grant. Without that grant it returns `approval_required` or a denial,
not a queued native command."

## What it does

The agent-facing **act** command. Given an **existing** active
`DesktopCommandApprovalGrant` (minted by a human via P5.5), `desktop_actuate`
enqueues exactly one bounded native command **through the shared
`enqueue_desktop_command` lifecycle**, bound to that grant. No grant → status
`approval_required`, **no command**. Wrong/expired/revoked/exhausted/wrong-session
grant → structured denial, **no command**.

It NEVER mints a grant, signs an envelope, or calls a native API. It is grant-
gated delegation: pre-validate the grant, then hand off to the existing enqueue
path which runs every native-control gate (per-capability flag, allowlist,
shell-connected, args-validation) and consumes the grant **at claim** (unchanged).

## Why it's safe (invariants)

1. **No minting.** Grant creation stays user-JWT-only (P5.5, untouched). actuate
   only *reads* a grant and enqueues against it. The internal/MCP actuate path
   takes `X-User-Id` only to *scope the grant lookup* (`grant.user_id == user`);
   it cannot forge a grant a real user didn't approve.
2. **No actuation enablement, no flag flips.** actuate delegates to
   `enqueue_desktop_command` → `_enqueue_native_control_command` →
   `_ensure_native_control_capability_enabled`, which requires the **default-off**
   per-capability flag (`pointer_control_enabled`/`keyboard_control_enabled`). For
   any tenant without it, enqueue raises 403 → actuate denies, **no command**.
   Only the operator tenant (flags already on, migration 169) reaches a pending
   command. actuate flips nothing.
3. **Missing grant → `approval_required`, no command.** A `grant_id` that does not
   resolve in the caller's tenant returns `approval_required`. A same-tenant
   grant owned by another user is a structured wrong-owner denial; a
   cross-tenant/nonexistent id stays uniform `approval_required`.
4. **Wrong grant → structured deny, no command.** A resolved grant that is
   revoked / expired / exhausted / for a different session / not native_control
   denies with the canonical `DesktopDenialCode` (`approval_revoked` /
   `approval_expired` / `approval_exhausted` / `approval_binding_mismatch`).
5. **Stop still governs.** Stop (#893) **revokes** the grant, so a post-Stop
   actuate finds a `revoked` grant → deny. A command enqueued before Stop stays
   preemptible by Stop (unchanged claim/complete path).
6. **Grant consumed at claim, not actuate.** actuate enqueues a `pending` command
   bound to `approval_id=grant.id`; the existing claim path matches + decrements
   `remaining_actions` + may flip the grant to `consumed`. One grant with
   `max_actions=N` allows N actuate→claim cycles.
7. **Display-safe.** Response + events carry command id/status/action/capability/
   bundle/approval ref only — never the actuation args (typed text, coords),
   screen bytes, OCR, titles, clipboard. (args persist in the command row, signed
   at claim — the existing D4 contract — but never in the response/events.)
8. **D5 respected.** The thin `actuate_command` lives in `services/desktop_act.py`;
   it *imports* `enqueue_desktop_command` + the canonical denial codes. No
   substantial code added to `desktop_control_service.py`.

## Contract

`actuate_command(db, *, tenant_id, user_id, session_id, grant_id, args=None,
nonce=None)` →
- **Look up the grant by `(id, tenant_id)` only — NOT by `(id, tenant_id, user_id)`.**
  A `(id, tenant_id, user_id)` filter would collapse a same-tenant wrong-owner
  grant into "not found" → `approval_required`, but the spec requires a *wrong-user
  grant* to **deny**. So:
  - grant not found in the tenant (nonexistent id, or a cross-tenant id) →
    `{status: approval_required}`, no command (uniform, no cross-tenant oracle).
  - grant found but `grant.user_id != user_id` (a real same-tenant grant owned by
    another user) → **explicit wrong-owner deny** (`approval_binding_mismatch`),
    no command. The same-tenant grant-id-existence signal is negligible (uuid4).
- then validate `session_id`, `risk_tier == native_control`,
  active/not-expired/not-revoked/remaining>0 → else structured deny.
- derive action/capability/target/shell from the grant; build
  `DesktopCommandEnqueue(approval_id=grant.id, payload={target, args})`; call
  `enqueue_desktop_command` (all native gates) → `{status: queued, command_id,…}`.
  Malformed `args` raise `ValueError` from the shared normalizer → caught and
  re-raised as a structured `422 invalid_actuation_args` (fixed reason, no echo).

## Surfaces

- Routes: `POST /desktop-control/commands/actuate` (user-JWT) +
  `POST /desktop-control/internal/commands/actuate` (internal-key + X-User-Id,
  for MCP — consumes a grant, never mints one).
- MCP: `desktop_actuate(session_id, grant_id, args, …)` (UUID-validated;
  `desktop_control` scope).
- Alpha CLI: `alpha desktop act --session --grant [--text|--x/--y|--key]` + typed
  core model + golden fixture. Pointer `--x/--y` are **normalized f64 in [0,1]**
  (the API signs micro-units); the three arg shapes (`--text`, `--x/--y`,
  `--key`) are **mutually exclusive at clap parse** (no silent precedence).

## Out of scope

`alpha desktop command audit` (read the approval+envelope audit trail) — a
read-only follow-up. Native actuation itself stays behind the default-off
per-capability flags + SP5/SP6.
