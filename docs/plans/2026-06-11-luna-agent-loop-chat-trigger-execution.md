# Luna P5.3-P5.5 Agent Loop And Chat Trigger Execution

Date: 2026-06-11
Status: design for next implementation slices
Inputs: `docs/report/2026-06-11-luna-computer-use-fable-review.md`, `docs/plans/2026-06-09-luna-phase5-general-app-control-design.md`, `docs/plans/2026-06-11-luna-secondary-pointer-background-control.md`

## Goal

Close the four remaining links between "Luna can be governed by the desktop
control substrate" and "Luna can receive a chat request, operate a macOS app,
and report back":

1. Agent-facing desktop observe/act tools exist and are scoped.
2. Operator Luna agents can reach those tools through `desktop_observe` and
   `desktop_control` tool groups.
3. Planner-safe perception content exists; raw pixels stay quarantined.
4. Chat can request a scoped desktop-control session, collect user approval,
   drive the loop, and report the audit-backed outcome.

This is operator-tenant autonomy only. PR5 per-tenant keys remains the hard gate
before any non-operator tenant receives actuation.

## Non-Negotiable Invariants

1. Alpha CLI is the kernel. Every Luna-facing desktop capability has an
   `alpha desktop ...` verb or typed Alpha/core contract in the same slice as
   the API route/MCP wrapper.
2. Tauri is the native shell and actuator, not the agent brain. The agent loop
   runs through AgentProvision chat/task routing and existing CLI runtimes.
3. Raw screenshot bytes, clipboard contents, OCR text, and window titles never
   reach a planning agent unless a reviewed planner-safe contract explicitly
   allows that field.
4. Native actuation requires all gates: master desktop control flag, action
   capability flag, tenant allowlist intersected with the global floor, TCC
   readiness, active shell/device/session, approval grant, Ed25519 envelope,
   Stop/Lock state, and native-boundary checks.
5. Stop is preemptive. Any active or queued desktop work must become visibly
   stopped/preempted in API events, Luna UI, and CLI/MCP surfaces.
6. New MCP tools are wrappers over the same service entrypoints as Alpha/API;
   no second business logic path.
7. Every state-mutating desktop path emits display-safe `session_events` and
   an audit event. Agent-visible responses carry audit refs, not raw secrets or
   raw perception bytes.
8. Agent-facing tools never mint approval grants. They may create a pending
   approval request, enqueue a command that references an already-approved
   grant, or poll status. The only grant writers are explicit user/operator
   approval surfaces and their server-side service methods.
9. General app control uses the secondary-pointer/background-control actuator
   contract. Existing global-cursor/frontmost paths may remain for their narrow
   legacy canaries, but they are not the P5.4 general app-control actuator.
10. Until the P5.5 approval UX exists, P5.4 agent loops are dry-run,
    pending-approval, or pre-granted test harness only. Chat-originated prompts
    must not reach native macOS actuation through internal-key-only grants.

## Current Gate State

Merged:

- D1 / PR #869: observe-path master gate and grant gate.
- SP1.5 / PR #870: background-control contract/security fixtures.
- D2 / PR #871: client `expires_at_ms`, fail-closed clock, same-owner pacing
  carry-forward, dead `canary_click` removal.

Pending release gate:

- D3 / PR #872: config drift, Ed25519 default, compose env precedence, local
  observations volume. CI is green and mergeable at `e87ea629`; Luna release-gate
  approval is still required before merge.

Open after D3:

- D4 test integrity gaps must be folded into the implementation slices below
  when they touch the same surface.
- D5 structural split and shared canonical fixtures must land before PR5 or any
  large expansion of `desktop_control_service.py`.

## Execution Ladder

### Slice 1: P5.3a-2 Redactor Driver

Purpose: make governed perception produce planner-safe artifacts for the first
time without exposing raw bytes to agents.

Implementation scope:

- Wire a redactor driver after governed screenshot upload or as a sweep-integrated
  worker over pending `perception_artifacts`.
- Connect the real `PERCEPTION_REDACTOR_ENABLED` flag; when off, artifacts stay
  non-planner-safe with a display-safe reason.
- Store redaction status transitions with tenant/session/device ownership.
- Fix the redactor lows that become live with the driver: TTL race, dangling
  `planner_safe` row after ambiguous failure, short-write handling, unknown
  region-kind fail-closed behavior, max-attempts coverage.

Tests:

- Unit tests for redactor state transitions and failure modes.
- API tests proving raw bytes never appear in event payloads, logs, fixtures, or
  agent-visible responses.
- Sweeper/driver tests for expired raw artifacts and pending redaction retries.
- One local operator smoke that creates a quarantined artifact and observes a
  planner-safe derivative without agent delivery.

Exit criteria:

- `perception_artifacts` can move from quarantined raw capture to planner-safe
  derivative under explicit flags.
- No agent-facing fetch path exists yet.

### Slice 2: P5.3b Planner-Safe Delivery And `alpha desktop observe`

Purpose: allow Luna's planner to observe only redacted, scoped content.

Implementation scope:

- Add a scoped planner-safe fetch service: tenant, session, shell/device, artifact
  id, expiry, and planner-safe status are required.
- Add `alpha desktop observe request|status|fetch` or the closest existing
  command shape, with typed success/denial models.
- Extend MCP observation tools so `desktop_observe_screen` can return planner-safe
  artifact metadata/content after scope checks, not only audit envelopes.
- Keep raw capture handles opaque and unprintable to agents.

Tests:

- CLI/core typed model tests.
- MCP wrapper tests for missing tool scope, wrong tenant/session/device,
  expired artifact, raw-not-planner-safe artifact, and successful planner-safe
  fetch.
- D4 privacy test: real `payload.args.text` may persist in the command row, but
  must be absent from events/display-safe payloads.

Exit criteria:

- Luna can call an observe tool and receive planner-safe perception only.
- No actuation tool is agent-facing yet.

### Slice 3: P5.4a Desktop Act Verbs And MCP Wrappers

Purpose: expose the governed command lifecycle to agents without bypassing the
existing signed envelope boundary.

Implementation scope:

- Add `alpha desktop command request|status|audit` and, if needed for clarity,
  `alpha desktop grant request`.
- Add MCP wrappers:
  - `desktop_request_grant`
  - `desktop_actuate`
  - `desktop_command_status`
- Gate wrappers with `desktop_control` scope and server-side action-derived
  capability class.
- `desktop_request_grant` creates a pending approval request only. It does not
  create an approval grant, does not sign an envelope, and does not call a native
  actuator.
- `desktop_actuate` accepts only a command plus a server-validated, existing
  approval grant. Without that grant it returns `approval_required` or a denial,
  not a queued native command.
- MCP wrappers enqueue only bounded, reviewed action shapes. They never call
  macOS APIs and never manufacture envelopes client-side.
- The API claim/approval/envelope lifecycle remains shared with the Tauri shell,
  but the P5.4 general app-control command must route to the
  secondary-pointer/background-control actuator contract, not the existing
  global-cursor/frontmost canary path.
- Responses are display-safe and include command id, status, denial code,
  approval status, and audit refs.

Tests:

- Tool-group/scope tests for `desktop_observe` versus `desktop_control`.
- Signed args integration test for the real WhatsApp path:
  `payload.args` -> signed `envelope.args` -> client completion/audit.
- Denial-completion lifecycle tests for missing grant, wrong command, expired
  grant, wrong device/session, action capability off, and allowlist revoke.

Exit criteria:

- Agent tools can request governed desktop commands, but only after approval and
  with the same API claim boundary the Tauri shell already uses.
- No agent-facing path can create approval grants or select the native actuator
  implementation.

### Slice 4: P5.4b Operator Luna Tool Groups And Agent Loop Scaffold

Purpose: let operator Luna run a bounded observe -> plan -> act -> observe loop.

Implementation scope:

- Grant `desktop_observe` and `desktop_control` only to the operator tenant's
  intended Luna agents after Luna/Codex approval.
- Add planner instructions/persona injection that explains the desktop loop,
  Stop semantics, approval requirements, and audit reporting.
- Add a loop coordinator that runs inside existing ChatCliWorkflow/task routing:
  observe, summarize state, propose action, request approval, wait for a
  server-created approval grant, enqueue act, wait for status, observe again,
  report.
- Log RL experience per desktop decision and per denial.
- Start with operator-only apps already in the global floor: Luna, TextEdit,
  WhatsApp.
- Before P5.5 lands, this coordinator may run only in dry-run, denied/no-op, or
  pre-granted test harness mode. It must not use internal-key-only approval
  grants to turn chat prompts into native actuation.

Tests:

- Agent routing tests proving non-desktop prompts do not trigger desktop tools.
- Tool availability tests for operator Luna only.
- Negative tests for non-operator tenants and Luna agents lacking tool groups.
- Loop dry-run test using denied/no-op command status before any broad actuation
  expansion.

Exit criteria:

- Luna can perform a governed operator-only loop in a controlled app with audit
  refs and visible Stop behavior once the explicit approval surface exists.
- Before that approval surface exists, Luna can prove observe -> plan ->
  approval-required/denied -> report-back without a native macOS call.

### Slice 5: P5.5 Chat Trigger, Approval UX, And Report-Back

Purpose: make "Luna, do X in app Y" work from the chat surface.

Implementation scope:

- Add desktop-intent detection in the chat path without hardcoding a single app:
  `enhanced_chat`, `agent_router`, and CLI session preparation receive explicit
  desktop capability context.
- Add user approval UX using the existing `human_approval` precedent:
  requested app/action, risk tier, bounded expiry, target session/device, Stop,
  deny, and audit preview.
- This UX is the first chat-originated writer of approval grants. It creates
  grants only after explicit user/operator approval and binds them to tenant,
  session, device, command/action, expiry, and risk tier.
- Surface progress through session events: observing, planning, awaiting
  approval, queued, claimed, acting, verifying, completed, denied, preempted.
- Final answer includes what was done, what was not done, and audit refs.

Tests:

- Chat trigger tests for desktop request, non-desktop request, ambiguous request,
  denied approval, Stop during queue, Stop during execution, and shell offline.
- Browser/Chrome tenant smoke for live chat routing.
- Installed Luna app Computer Use smoke for permission readiness, approval UX,
  Stop preemption, and final report.

Exit criteria:

- Operator Luna can receive a chat prompt, ask for scoped approval, operate an
  allowlisted macOS app through the governed path, verify by observe, and report
  back with audit refs.

## Council And Delegation

Luna:

- Product/operator lead and release gate.
- Must pull the exact branch/PR under review and answer `MERGE`, `REVISE`, or
  `BLOCK` for release gates.
- Owns UX acceptance: permission readiness, approval clarity, Stop confidence,
  and business-operation impact.

Claudia:

- Heavy implementation and adversarial review.
- Suggested lanes:
  - P5.3 redactor driver and planner-safe delivery tests.
  - P5.4 Alpha CLI/core typed models and MCP wrapper tests.
  - D4/D5 structural/test-debt slices when they block the feature path.

Codex:

- Orchestrates branches, PR order, local verification, GitHub Actions gates,
  installed Luna/Chrome smoke via Computer Use, and plan updates.
- Does not merge without Luna gate on Luna computer-use PRs.

## Release And Validation Gates

Each PR must include:

- `git diff --check`.
- Focused API/CLI/MCP/Tauri tests for touched surfaces.
- GitHub Actions green or a documented non-blocking skip reason.
- Luna release-gate review for any Luna-facing UX/control behavior.
- Computer Use validation for installed app behavior when a Luna build changes.

Before marking the feature E2E complete:

- Pull/install the latest Luna release build locally.
- Verify TCC panel state and permission modal with Computer Use.
- Verify Chrome/live tenant chat trigger.
- Verify Luna Tauri chat trigger.
- Verify Stop preemption.
- Verify final report carries audit refs and no raw screenshot or typed secret.
- Verify the Docker `_work` mount gate returns no output.

## Open Risks

1. PR5 per-tenant keys is still required before non-operator actuation.
2. `desktop_control_service.py` must be split before more large feature growth.
3. Canonical Python/Rust tables need a shared fixture to avoid drift.
4. Alpha CLI is currently installed locally but unauthenticated in this Codex
   environment; Luna Desktop remains the active review channel unless auth is
   explicitly restored.
5. The D3 PR body has a stale original table entry, but the correction comment
   and diff reflect the true non-API signing-boundary fix.
