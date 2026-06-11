# P5.5 — user approval surface for desktop approval requests

Status: design + implementation (this slice). Lane: Luna computer-use P5.5.
Builds on: P5.4b pending request `desktop_approval_requests` (#895), grant
substrate `create_desktop_approval_grant` (internal), Stop/preempt (#893).

## Why / what

#895 lets an agent record a **pending** `desktop_approval_requests` row and poll
it. P5.5 adds the **human** approve/deny half: an authenticated user converts a
pending request into exactly one **bounded active `DesktopCommandApprovalGrant`**
(approve), or terminally denies it (deny). This is the only path that turns a
request into an actionable grant — and it is human-only.

## Hard invariants

1. **Human-only, authenticated.** Approve/deny/list routes are user-JWT
   (`deps.get_current_active_user`). They reject `MCP_API_KEY`/internal-key callers
   and never read a caller-supplied `X-User-Id`. The grant owner is the
   authenticated principal (`current_user.id`).
2. **No actuation, no flag flips.** Approving mints a grant; it does NOT enable
   pointer/keyboard tenant flags and does NOT enqueue/claim a command. The grant is
   inert until the (default-off) per-capability flag + an enqueue/claim — neither
   touched here. Minting a native-control grant ≠ actuation.
3. **Exactly one grant, fail-closed.** Approve is row-locked
   (`SELECT … FOR UPDATE`) + status-checked; a duplicate/concurrent approve sees
   `status != 'pending'` → 409 (`request_not_pending`), never a second grant.
   Approve + request-update commit in **one transaction**.
4. **Deny is terminal + audit-visible.** Sets `status='denied'`, `decided_*`,
   emits `desktop_grant_denied`; creates no grant.
5. **Pending rows stay unclaimable.** Pending requests live in their own table;
   the claim path only ever consumes `DesktopCommandApprovalGrant.status=='active'`.
   Tested: 0 active grants before approve, exactly 1 after.
6. **Bound + scoped.** The minted grant binds tenant, session, shell+device (from
   **live** presence at approve time), capability/risk_tier (`native_control`),
   requested target app (`{bundle_id, action}`, allowlist-gated), and expiry.
   Cross-tenant / wrong-user / expired requests are denied (uniform not-found or
   structured denial).
7. **Display-safe.** Responses + `desktop_grant_approved`/`denied` events carry
   ids/status/action/capability/reduced-target/grant-presence only — never raw
   payloads, screen bytes, OCR, titles, clipboard, envelopes, or the deny free-text
   (event-only, capped).
8. **D5 respected.** All new logic in the existing thin `services/desktop_act.py`
   (#895) — reuses the shared validation helpers
   (`_require_native_control_target_binding`, `_select_connected_shell`,
   `_capability_matches_risk_tier`, `_ensure_*`) and constructs the grant inline so
   the whole approve is one atomic, idempotent transaction;
   `desktop_control_service.py` is only imported from, never edited.

## Surfaces

- Service (`desktop_act.py`): `list_pending_approval_requests`,
  `approve_desktop_grant_request`, `deny_desktop_grant_request`
  (`get_desktop_grant_request_status` already exists from #895). New denial codes
  `request_not_pending`, `request_expired` on the existing closed enum.
- Routes (user-JWT, `desktop_control.py`):
  `GET /desktop-control/grants/requests[?session_id=]`,
  `POST /desktop-control/grants/requests/{id}/approve`,
  `POST /desktop-control/grants/requests/{id}/deny`.
- Alpha CLI: `alpha desktop approvals list|approve|deny` + typed core models.
- Events: `desktop_grant_approved`, `desktop_grant_denied` (the #895
  `desktop_grant_requested` already serves the *awaiting_approval* signal).

## Out of scope (follow-ups)

- **MCP:** a read-only `desktop_list_approval_requests` could help the agent loop
  *see* pending requests, but is deferred to keep this slice tight; approve/deny
  stays human-only (no MCP grant minting, per the gate).
- **Stop → cancel-pending:** Stop (#893) revokes active grants + preempts commands;
  wiring it to also cancel *pending requests* touches the #893 Stop path and is a
  separate follow-up. Pending requests already lazily project to `expired` past TTL.
