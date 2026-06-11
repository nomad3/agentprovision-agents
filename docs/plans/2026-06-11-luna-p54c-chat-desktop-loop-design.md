# P5.4c — chat-triggered desktop loop (grant-ref on status + planner guidance)

Status: design + smallest make-it-work slice. Lane: Luna computer-use. Builds
on: P5.4b pending request (#895), P5.5 approve/deny (#896), P5.4b
`desktop_actuate` (#898), the agent-loop prompt scaffold (#886), Stop (#893).
Spec: plan Slice 5 (`2026-06-11-luna-agent-loop-chat-trigger-execution.md`,
lines 440-518) — "a loop coordinator that runs inside existing
ChatCliWorkflow/task routing: observe, summarize state, propose action, request
approval, wait for a server-created approval grant, enqueue act, wait for
status, observe again, report."

## The seam decision (the part that was ambiguous)

A chat turn is **one CLI subprocess**, not a server-driven loop. Trace:
`chat.post_user_message` → `_generate_agentic_response` →
`cli_session_manager` (generates the instruction markdown + MCP config) →
Temporal `ChatCliWorkflow` → `execute_chat_cli` **activity = a single
`claude -p` / `codex` / … invocation**. The CLI itself drives the MCP
tool-calling loop during that one turn. There is no server-side step machine
around the turn (the only post-turn server work is the fire-and-forget
`PostChatMemoryWorkflow` — memory/scoring, not control).

So the "loop coordinator" the plan asks for **is the planner prompt + the
already-merged MCP tool surface**, exactly as the plan says ("runs inside
existing ChatCliWorkflow/task routing"). It is **not** a new Temporal workflow.
All governance stays server-side and unchanged: grants mint only via the P5.5
user-JWT approve route; `actuate` re-validates owner/session/expiry/revocation
and runs every native gate (default-off per-capability flag, allowlist,
shell-connected) at enqueue + claim; Stop revokes grants.

Decision: **drive the loop from the planner prompt over the merged tools. Add
no server coordinator, no new workflow, no new mint path.**

## The gap that blocks "make it work"

The agent cannot complete the loop today. After a human approves out-of-band
(P5.5), the agent's only reachable read surface is the status poll
(`desktop_request_status` → `desktop_act.get_desktop_grant_request_status` →
`_display_safe_request`). That projection returns `grant_present: bool` but
**not the `grant_id`**. The minted `grant_id` is only returned to the **human**
in the approve response (`grant_approval.approved.json` via `_grant_summary`).
A CLI-subprocess agent polls tools — it cannot read the SSE stream — so it has
no way to learn the `grant_id` it must pass to `desktop_actuate`. The plan
requires the agent to "wait for a server-created approval grant, enqueue act";
that needs an agent-reachable **reference** to the grant.

## The fix (smallest primitive that closes the loop)

Expose `grant_id` (string, `null` until approved) on the **owner-scoped** status
projection `_display_safe_request`. The status poll is already filtered by
`tenant_id` **and** `user_id`, so only the requesting owner ever sees it; a
wrong tenant/owner/id stays the uniform `request_not_found`. No new mint path,
no grant payload — just the id, which is the contract's allowed "approval ref".

Why it discloses nothing new and grants nothing:
- The **same owner** already receives the full grant summary (incl. `grant_id`)
  in the approve response. The status poll is that owner viewing their own
  request; reflecting the id back is not a new disclosure.
- `grant_id` is a `uuid4`. Knowing it grants nothing: `actuate` looks up by
  `(id, tenant)` then enforces `grant.user_id == caller`, `session`, risk tier,
  active/not-expired/not-revoked/remaining>0, **and** the default-off
  per-capability native flag. For any tenant without the flag, `actuate` denies
  and queues no command. The grant_id is a handle, not an authorization.
- The status projection stays display-safe: ids/status/action/capability/
  bundle/refs only. `deny_unknown_fields` on the Rust mirror still rejects any
  smuggled payload/ocr/title/clipboard/text field.

## Planner prompt change

Today the `desktop_control` block in `cli_session_manager.generate_cli_instructions`
is dry-run-only and ends with "Do not call pointer, click, keyboard,
approval-grant, or native actuation paths in this phase." Now that
`desktop_actuate` (#898) is merged, extend that block (control-capable agents
only) to describe the **governed loop** over the existing tools:

1. `desktop_request_grant(action, target_bundle_id)` → a **pending** request.
2. Tell the user a human approval is required; **you cannot approve your own
   request**. Poll `desktop_request_status(request_id)` until `status` is
   `approved` and a `grant_id` is present (or `denied`/`expired` → stop).
3. `desktop_actuate(session_id, grant_id, args)` → one bounded command, or a
   structured denial (`approval_required` / `approval_*`) → report and stop.
4. Poll `desktop_command_status(command_id)` to terminal status.
5. Report back **display-safe only**: action class, capability, outcome/status,
   denial code, command id, and audit/event refs — never OCR text, window
   titles, contact names, clipboard values, typed text, or screen content.
6. `desktop_stop_commands` cancels in-flight work; a Stop revokes the grant.

Observe-only agents are unchanged (no act loop). The dry-run/observe guidance
stays. The block still fails closed without a `session_id`. The operator-only
restriction needs no tenant check in the prompt: `desktop_control` is granted
only to the operator Luna rows (#885), and `actuate` fails closed for any
tenant without the per-capability flag, so non-operator agents never reach a
native command even if the words were present.

## Invariants (must hold)

1. No agent/MCP/internal path mints a grant. Only the P5.5 user-JWT approve
   route mints. `request_desktop_grant`, the status poll, and `actuate` create
   zero `DesktopCommandApprovalGrant` rows.
2. Native pointer/keyboard flags are untouched (default-off everywhere except
   the operator tenant's existing migration-169 state). This slice flips none.
3. Allowlist untouched; no native actuation implementation added (the Tauri
   client does native execution behind SP5/SP6; the API only enqueues).
4. Stop still revokes; post-Stop actuate finds a `revoked` grant → deny.
5. Report-back + every session event stay display-safe (the `grant_id` is an
   approval ref, allowed by the contract).
6. D5 respected — change lives in the existing `_display_safe_request` +
   `cli_session_manager` prompt; `desktop_control_service.py` is not touched.

## File-level seams (this PR)

- `apps/api/app/services/desktop_act.py` — `_display_safe_request` adds
  `grant_id` (`str(request.grant_id)` or `None`). One line; the approve path
  already merges `_grant_summary` (same `grant_id`), so its shape is unchanged.
- `apps/api/app/services/cli_session_manager.py` — extend the
  `has_desktop_control` prompt block with the governed loop (replaces the blanket
  "do not call … approval-grant …" line for control-capable agents; keeps the
  no-self-approval + display-safe report-back + Stop lines).
- `docs/contracts/desktop-control/grant_request.pending.json` — add
  `"grant_id": null`. New `grant_request.approved.json` — status-poll-after-
  approval shape (`status: approved`, `grant_present: true`, `grant_id` set).
- `apps/agentprovision-core/src/desktop.rs` — `DesktopGrantRequest` gains
  `#[serde(default)] grant_id: Option<String>`; add an approved-status
  round-trip test; payload-rejection tests still hold.
- `apps/agentprovision-core/tests/desktop_contract.rs`,
  `apps/agentprovision-cli/tests/desktop_contract.rs` — wire the new
  approved-status fixture through the typed core path.
- `apps/api/tests/api/v1/test_desktop_grant_request.py` (+ approval test) —
  assert `grant_id` is `None` while pending, set after approve, and that the
  status poll / request path mint **no** grant.
- `apps/mcp-server/tests/test_desktop_control_contract.py` — assert
  `desktop_request_status` passes `grant_id` through.
- `apps/api/tests/test_cli_instructions_desktop_context.py` — assert the loop
  guidance renders for `desktop_control`, is absent for observe-only, and keeps
  the no-self-approval + display-safe report-back lines.

## PR ladder (later rungs, out of this slice)

- **PR2 — readiness probe**: a `permission_not_ready` fresh Luna-client
  permission probe before enqueue (plan lines 466-468). Does not exist yet; the
  current slice relies on `actuate`'s fail-closed shell/flag gates instead.
- **PR3 — desktop RL experience**: byte-free `rl_experience` per desktop
  decision/denial (denial code, action class, capability, outcome, command id,
  audit refs — no OCR/title/clipboard/text). No desktop RL logging exists today.
- **PR4 — report-back leak fixtures**: planner-safe OCR/contact/title fixtures
  proving the report-back path quotes none of them; dashboard approve affordance
  if the human approval UX needs surfacing beyond the existing approvals routes.

## Out of scope

Native pointer/keyboard execution (SP5/SP6 + Tauri client), tenant flag flips,
allowlist changes, signing secrets, Docker/macOS/release/merge. `alpha desktop
command audit` (read the approval+envelope trail) remains a read-only follow-up.
