# P5.4d - Luna permission readiness before desktop enqueue

Status: implementation slice. Lane: Luna macOS computer-use.

## Goal

Before a chat-driven Luna agent can enqueue a native-control command, the API
must have a fresh permission-readiness signal from the target Luna desktop shell.
If Screen Recording or Accessibility is missing, stale, denied, or unknown for
pointer/keyboard control, `desktop_actuate` must return `permission_not_ready`
and create no `desktop_commands` row.

This makes the user-visible Luna permission onboarding state part of the
agent-control gate. It does not grant permissions, modify macOS TCC, flip tenant
feature flags, sign envelopes, or enable native actuation.

## Data Flow

1. Luna Tauri already computes permission readiness through
   `control_get_safety_state`.
2. `useShellPresence` includes a sanitized `permission_readiness` object during
   `/api/v1/presence/shell/register` heartbeats.
3. The API presence service stores only canonical status fields plus a
   server-side `observed_at` timestamp per shell.
4. `enqueue_desktop_command` checks the selected live shell before native-control
   enqueue.
5. Missing, stale, or non-`granted` required probes raise structured
   `permission_not_ready`; no command row is created.

## Required Permissions

- `pointer_control`: `screen_recording`, `accessibility`
- `keyboard_control`: `screen_recording`, `accessibility`
- `background_control`: `accessibility`

`automation_system_events`, `input_monitoring`, camera, and microphone remain
reported through presence for UX/diagnostics but are not required for this
native-control enqueue gate.

## Contract

- `permission_not_ready` is added to the canonical desktop denial-code set.
- Python, Luna Tauri, Alpha core, and Alpha CLI typed mirrors must deserialize or
  map the code fail-closed.
- The denial reason is fixed and display-safe:
  `desktop permission readiness <state>; <action> denied`.

## Tests

- API actuate tests: missing readiness, denied readiness, and stale readiness all
  return `permission_not_ready` and create no command rows.
- API lifecycle tests: normal native-control enqueue fixtures include granted
  readiness.
- Luna hook test: shell registration sends sanitized statuses, not reasons or
  identity details.
- Tauri/core/CLI contract tests: `permission_not_ready` is recognized by the
  mirrored denial-code contract.

## Out Of Scope

- Native pointer/keyboard execution.
- macOS permission mutation or TCC database writes.
- Signing/notarization.
- Release install validation.
- Multi-tenant per-key rollout.
