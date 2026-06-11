# P5.4b-req — Agent-facing pending desktop approval request

Status: design + implementation (this slice). Lane: Luna computer-use P5.4.
Builds on: P5.4a dry-run substrate (#879), P5.4b status (#881), P5.4 bootstrap
(#883/#884), operator tool groups (#885). Inputs:
`2026-06-11-luna-agent-loop-chat-trigger-execution.md` Slice 4,
`2026-06-11-luna-computer-use-fable-review.md` §5b (G-1).

## Why this slice

The dry-run/no-op request→poll path is already shipped end to end
(`desktop_background_app_control_dry_run` → `desktop_command_status` → `no_op`).
The unbuilt, genuinely-new agent-facing capability from Slice 4 is the
**pending-approval branch**: `desktop_request_grant` — "creates a pending
approval request only. It does not create an approval grant, does not sign an
envelope, and does not call a native actuator." (plan Slice 4).

This is the smallest slice that closes the first half of Fable G-1 ("no
agent-facing act tools") with an intrinsically safe outcome: an agent (Luna)
**asks** for permission to run a native desktop action; the request sits
`pending` for a human to approve later (P5.5); the agent can **poll** it. Nothing
actuates, no grant is minted, no envelope is signed.

## Invariants (safety)

1. **No actuation.** The request never enqueues a command, never calls macOS, never
   signs an envelope.
2. **No grant minting.** Grant creation stays internal-key-only
   (`create_desktop_approval_grant`, untouched). A pending request lives in a
   **separate** table and is invisible to the claim path (which only matches
   `DesktopCommandApprovalGrant.status == "active"`), so it can never authorize a
   native action.
3. **Native-control actions only.** Requests are accepted only for the four
   native-control actions (`pointer_move`, `pointer_click`, `keyboard_type`,
   `keyboard_key_chord`) — the actions that will need a user grant. Observe/dry-run
   need no grant, so requesting one for them is rejected.
4. **Fail-closed gates.** Master `desktop_control_enabled` re-checked at request
   time; session ownership enforced; tenant/session/shell scoped.
5. **Display-safe.** Responses + session events carry ids/status/action/capability/
   reduced target only — never raw payloads, screen bytes, OCR, titles, clipboard.
6. **D5 respected.** All new logic lives in a new thin module
   (`services/desktop_act.py`) + new model; `desktop_control_service.py` is only
   *imported* from (helpers reused), never edited.

## Data — `desktop_approval_requests` (migration 176)

New table, additive. Columns: `id`, `tenant_id`, `user_id` (requesting principal),
`session_id`, `shell_id`, `device_id?`, `action`, `capability`,
`target_binding` (JSONB, reduced — `{bundle_id, ...}`), `reason?` (capped),
`status` (`pending`→`approved`/`denied`/`expired`/`cancelled`, default `pending`),
`requested_by_user_id`, `decided_by_user_id?`, `grant_id?` (FK set when P5.5 mints
a grant), `created_at`, `expires_at`, `decided_at?`. Indexes on
`(tenant_id, status)` and `(session_id)`.

## Surfaces

- Service `services/desktop_act.py`: `request_desktop_grant(...)` +
  `get_desktop_grant_request_status(...)`.
- Routes (thin, `desktop_control.py`):
  - `POST /desktop-control/grants/request` (user JWT) — Alpha.
  - `GET /desktop-control/grants/requests/{id}` (user JWT) — Alpha.
  - `POST /desktop-control/internal/grants/request` (internal-key + X-Tenant-Id +
    X-User-Id) — MCP.
  - `GET /desktop-control/internal/grants/requests/{id}` (internal-key) — MCP.
- MCP tools (in `desktop_control` group): `desktop_request_grant`,
  `desktop_request_status` (UUID-validate ids — SSRF lesson from #891).
- Alpha CLI: `alpha desktop grant request|status` + typed core models
  (`deny_unknown_fields`, display-safe).

## Out of scope (exact next PR)

`desktop_actuate` — the agent-facing act verb that, given a command + a
server-validated **existing** grant, enqueues via the shared lifecycle, and
without a grant returns `approval_required`. It depends on the P5.5 user
grant-approval surface (which flips `pending → approved` and mints the grant)
existing first. Native pointer/keyboard actuation stays gated behind SP5/SP6.
