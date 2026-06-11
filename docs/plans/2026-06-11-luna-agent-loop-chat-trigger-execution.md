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
   capability flag, tenant allowlist intersected with the global floor,
   permission readiness from a fresh Luna shell preflight, secure-input idle,
   active shell/device/session, approval grant, Ed25519 envelope, Stop/Lock
   state, and native-boundary checks. TCC readiness is a client-enforced loop
   precondition and audit signal; the server must deny stale or failed preflight
   as `permission_not_ready`, but it cannot prove macOS TCC state by itself.
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
   approval surfaces and their user-authenticated server-side service methods.
   A grant-writing route must not accept `MCP_API_KEY` alone, must derive the
   owner from the authenticated principal rather than `X-User-Id`, and must bind
   the grant to tenant, user, session, device, command/action, expiry, and risk.
9. General app control uses the secondary-pointer/background-control actuator
   contract. Existing global-cursor/frontmost paths may remain for their narrow
   legacy canaries, but they are not the P5.4 general app-control actuator.
10. Until the P5.5 approval UX exists, P5.4 agent loops are dry-run,
    pending-approval, or pre-granted test harness only. The pre-granted harness
    setup must originate outside the chat path; chat-originated prompts must not
    reach native macOS actuation through internal-key-only grants.
11. Until PR5 binds tenant/user identity into per-tenant Ed25519 signing keys,
    exactly one operator tenant may have actuation flags, the global floor, and
    agent tool groups enabled for native control. This is a data-seeded
    operational invariant over `tenant_features`, allowlists, and migrations
    169/170/172; it is not a runtime fleet-wide guard until PR5.

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
  This is a release/config hygiene gate, not the P5.4 native-actuator
  prerequisite; do not tag Slices 3-6 as blocked on D3 once the operator
  environment is already configured.

Open after D3:

- D4 test integrity gaps must be folded into the implementation slices below
  when they touch the same surface.
- D5 structural split and shared canonical fixtures must land before Slice 4 or
  any large expansion of `desktop_control_service.py`; do not defer this to PR5.

Ordering rule:

- P5.3 perception must land before planner delivery.
- P5.4a is the secondary-pointer/background actuator from
  `2026-06-11-luna-secondary-pointer-background-control.md` (SP2-SP6), not the
  agent-facing Alpha/MCP wrapper layer.
- P5.4b exposes act verbs after the actuator contract exists.
- P5.4c wires the operator Luna loop.
- P5.5 adds chat trigger and explicit user approval UX.

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
- Status 2026-06-11: draft PR #880 (`claudia/p53a-redactor-driver`) wires the
  driver loop, flag gate, cleanup race fixes, and byte-free redaction events.
  Codex/Luna review found that the original unknown-region reason echoed
  engine-supplied text into status metadata; commit `af4e5deb` fixes this with
  a fixed `unknown_region_kind` code and regression coverage. PR #880 remains
  draft because `_load_engine()` still returns `None`: the loop is correct but
  dormant, so the exit criterion "quarantined raw capture -> planner-safe
  derivative" is not satisfied yet.

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

- Add a scoped planner-safe fetch service: tenant, session, shell/device,
  artifact id, expiry, and planner-safe status are required.
- Fetch must read only `redacted_storage_path`, never raw `storage_path`, and
  must deny unless `redaction_status == planner_safe` and `raw_deleted_at IS NOT
  NULL`.
- Fetch resolves the canonical id-derived jailed path for the redacted artifact;
  it must not trust a stored path string as the filesystem authority.
- Re-check the master `desktop_control_enabled` flag at fetch time; the fetch
  service does not inherit the #869 observe/approval gates by accident.
- Add `alpha desktop observe request|status|fetch` or the closest existing
  command shape, with typed success/denial models.
- Add thin user-JWT + device-token v1 routes for Alpha observe fetch/status if
  the current implementation is internal-key-only. Alpha CLI must not call
  `/internal/*` desktop routes.
- Extend MCP observation tools so `desktop_observe_screen` can return
  planner-safe artifact metadata/content after scope checks, not only audit
  envelopes.
- Keep raw capture handles opaque and unprintable to agents.

Tests:

- CLI/core typed model tests.
- MCP wrapper tests for missing tool scope, wrong tenant/session/device,
  expired artifact, raw-not-planner-safe artifact, and successful planner-safe
  fetch.
- Fetch-source tests proving raw `storage_path` is never served, `raw_deleted_at`
  is required, and `desktop_control_enabled=false` denies even for a
  planner-safe artifact.
- D4 privacy test: real `payload.args.text` may persist in the command row, but
  must be absent from events/display-safe payloads.

Exit criteria:

- Luna can call an observe tool and receive planner-safe perception only.
- No actuation tool is agent-facing yet.

### Slice 3: P5.4a Secondary-Pointer/Background Actuator

Purpose: create the native general app-control actuator before exposing broad
agent-facing act tools.

Implementation scope:

- Implement SP2-SP6 from
  `2026-06-11-luna-secondary-pointer-background-control.md` in order:
  - SP2 target-app resolver with bundle/process/window identity proof and
    allowlist/global-floor intersection.
  - SP3 AX probe and dry-run, with no native actuation.
  - SP4 overlay pointer/HUD as a subscriber only; Stop request is allowed, but
    resume/approve/replay/lease extension is not.
  - SP5 AX action path behind a default-off operator-only flag.
  - SP6 PID/window-scoped fallback behind a separate default-off review gate.
- Keep SP7 (retiring the frontmost/global-cursor gate) out of this slice until
  SP2-SP6 pass and receive a separate Luna/Codex review.
- Re-check Stop, Lock, secure input, target drift, app quit, tenant flags,
  target allowlist, approval grant, and envelope immediately before each native
  call.
- Define a first-class server-recognized dry-run/no-op command mode before
  canary execution. The claim path must refuse to wrap this mode in a native
  envelope, and API/session events must make it distinguishable from a denied
  real actuation. The dry-run lifecycle is claimable and Stop-preemptible
  (`pending -> claimed -> running -> no-op`); it is not modeled as an
  immediate-terminal denied row.
- Status 2026-06-11: first server/MCP dry-run slice landed in PR #879
  (`codex/luna-p54a-background-control`, merge `cd624503`):
  `background_app_control_dry_run` is a real command action with
  `background_control` capability, `background_control_enabled` tenant gate,
  API route validation, and MCP tool
  `desktop_background_app_control_dry_run`. Claim emits a claimed event then
  terminal `no_op`, persists no native command envelope, consumes no approval
  grant, and remains Stop-preemptible while pending. This is a working
  dry-run lifecycle only; it does not enable AX, PID, pointer, or keyboard
  native actuation.
- Use the SP1.5 contract/security fixtures as executable denial vocabulary.
- Prove global cursor functions are not called by background-control commands.

Tests:

- Contract tests for target resolver, target drift, app quit, revoked allowlist,
  flag-off, Stop/Lock, and secure-input denial (`secure_input_active`) before
  any native call.
- Dry-run/no-op tests proving the command status is explicit, audit-visible, and
  the native envelope path is unreachable.
- Stop-during-dry-run test proving the no-op lifecycle uses the same
  status-based Stop/preempt path as native-capable commands.
- Native-boundary tests proving the operator cursor is not moved by the
  background actuator.
- Overlay/HUD tests proving it can request Stop but cannot approve, resume,
  mutate, replay, or extend leases.
- Operator-only canary smoke in denied/dry-run mode before enabling any AX
  action flag.

Exit criteria:

- The signed background actuator contract exists, is default-off, and can deny
  or dry-run against an allowlisted operator app without using the global cursor.
- Only dry-run/no-op agent-facing act tooling is exposed until this slice is
  green; real native actuation remains behind later review gates.

### Slice 4: P5.4b Desktop Act Verbs And MCP Wrappers

Purpose: expose the governed command lifecycle to agents without bypassing the
existing signed envelope boundary.

Implementation scope:

- Prerequisite: D5 structural split has landed, or this slice is limited to
  contract/tests only. Do not add substantial code to
  `desktop_control_service.py` before D5.
- Prerequisite: Slice 3 background actuator contract is green. Wrappers may
  target fixed canary/no-op actions until SP5/SP6 actuation is explicitly
  enabled.
- Add `alpha desktop command request|status|audit` and, if needed for clarity,
  `alpha desktop grant request`.
- Add thin user-JWT + device-token v1 routes for command request/status/audit
  and pending grant request if the existing route is internal-key-only. Alpha
  CLI uses those user-facing routes and never calls `/internal/*`.
- Add MCP wrappers:
  - `desktop_request_grant`
  - `desktop_actuate`
  - `desktop_command_status`
- Gate wrappers with `desktop_control` scope and server-side action-derived
  capability class.
- `desktop_request_grant` creates a pending approval request only. It does not
  create an approval grant, does not sign an envelope, and does not call a native
  actuator.
- Grant creation itself must be exposed only through the P5.5 user approval
  surface or an equivalent user-JWT + device-token route. It must reject
  `MCP_API_KEY`-only callers and derive the user from the authenticated
  principal, not from caller-supplied headers.
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
- Status 2026-06-11: branch `codex/luna-p54b-command-status` implements the
  first read-only status/audit part of this slice. It adds a tenant/user-scoped
  command status service, user-JWT route `GET /desktop-control/commands/{id}`,
  read-only internal status route for MCP, and MCP tool
  `desktop_command_status`, with the status tool granted through the
  `desktop_control` tool group. The response intentionally omits raw command
  payloads, signed envelopes, approval payloads, screen bytes, clipboard text,
  and native actuation args. This lets Luna queue a dry-run and report its
  audited terminal state, but it does not add approval grant creation, Alpha CLI
  verbs, or real native actuation.

Tests:

- Tool-group/scope tests for `desktop_observe` versus `desktop_control`.
- Signed args integration test for the real WhatsApp path:
  `payload.args` -> signed `envelope.args` -> client completion/audit.
- Denial-completion lifecycle tests for missing grant, wrong command, expired
  grant, wrong device/session, action capability off, and allowlist revoke.
- D4 test-integrity guard proving the real claim path uses `SELECT ... FOR
  UPDATE` or the production equivalent under concurrent claim/revoke, not only
  SQLite green-path tests.
- Runtime permission tests proving forward-declared `desktop_control` tool names
  cannot be invoked without a registered MCP tool and a matching tool group.
- Stop/preempt test on `desktop_actuate` itself, not only the downstream command
  lifecycle.
- Grant-route auth test proving an MCP/internal-key-only caller cannot mint an
  approval grant or forge owner identity through `X-User-Id`.

Exit criteria:

- Agent tools can request governed desktop commands, but only after approval and
  with the same API claim boundary the Tauri shell already uses.
- No agent-facing path can create approval grants or select the native actuator
  implementation.

### Slice 5: P5.4c Operator Luna Tool Groups And Agent Loop Scaffold

Purpose: let operator Luna run a bounded observe -> plan -> act -> observe loop.

Implementation scope:

- Grant `desktop_observe` and `desktop_control` only to the operator tenant's
  intended Luna agents after Luna/Codex approval.
- Add planner instructions/persona injection that explains the desktop loop,
  Stop semantics, approval requirements, secure-input denial, and audit
  reporting.
- Add a loop coordinator that runs inside existing ChatCliWorkflow/task routing:
  observe, summarize state, propose action, request approval, wait for a
  server-created approval grant, enqueue act, wait for status, observe again,
  report.
- Log RL experience per desktop decision and per denial using byte-free fields
  only: denial code, action class, capability, outcome, command id, and audit
  refs. Do not persist OCR text, window titles, contact names, clipboard values,
  typed text, or planner-safe artifact text in `rl_experience.state_text`,
  `rl_experience.state`, action fields, embeddings, or free-form metadata.
- Start with operator-only apps already in the global floor: Luna, TextEdit,
  WhatsApp.
- Before P5.5 lands, this coordinator may run only in dry-run, denied/no-op, or
  pre-granted test harness mode. It must not use internal-key-only approval
  grants to turn chat prompts into native actuation.
- Before enqueue, the coordinator must request a fresh Luna client
  permission-readiness probe for the target shell/device. Missing, stale, or
  denied permissions produce `permission_not_ready` and no command row is queued.
- Report-back from this coordinator is constrained to action summaries,
  outcome/status, denial codes, and audit refs. It must not quote planner-safe
  OCR text, window titles, contact names, clipboard values, or raw observed
  screen content.

Tests:

- Agent routing tests proving non-desktop prompts do not trigger desktop tools.
- Tool availability tests for operator Luna only.
- Negative tests for non-operator tenants and Luna agents lacking tool groups.
- Loop dry-run test using denied/no-op command status before any broad actuation
  expansion.
- Report-back leak test using planner-safe OCR/contact/window-title fixtures:
  final agent text must include only action/outcome/audit refs.
- RL-leak test using the same OCR/contact/window-title fixtures proving
  `rl_experience` rows and embeddings receive only byte-free decision fields.
- Permission-readiness test proving stale or denied preflight returns
  `permission_not_ready` before enqueue and before any claim/native boundary.

Exit criteria:

- Luna can perform a governed operator-only loop in a controlled app with audit
  refs and visible Stop behavior once the explicit approval surface exists.
- Before that approval surface exists, Luna can prove observe -> plan ->
  approval-required/denied -> report-back without a native macOS call.

### Slice 6: P5.5 Chat Trigger, Approval UX, And Report-Back

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
- Grant creation uses the authenticated user/session/device context. The route
  must reject `MCP_API_KEY`-only callers and must not accept a caller-supplied
  `X-User-Id` as the grant owner.
- Surface progress through session events: observing, planning, awaiting
  approval, queued, claimed, acting, verifying, completed, denied, preempted.
  Each event goes through `_publish_display_safe_session_event` or the same
  allowlisted display-safe serializer.
- Final answer includes what was done, what was not done, denial/status, and
  audit refs only. It must not transcribe observed app content unless a separate
  reviewed disclosure contract allows that exact field.

Tests:

- Chat trigger tests for desktop request, non-desktop request, ambiguous request,
  denied approval, Stop during queue, Stop during execution, and shell offline.
- Chat report tests proving OCR text, window titles, contact names, clipboard
  values, and typed secrets are absent from final free text and events.
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
  - P5.4a SP2-SP6 secondary-pointer/background actuator implementation and
    native-boundary tests.
  - P5.4b Alpha CLI/core typed models, user-JWT v1 routes, and MCP wrapper
    tests.
  - D4/D5 structural/test-debt slices before they block the feature path.

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
- Verify exactly one operator tenant has pointer/keyboard actuation flags,
  allowlist entries, and Luna `desktop_control` tool groups enabled until PR5.
- Verify TCC panel state and permission modal with Computer Use.
- Verify Chrome/live tenant chat trigger.
- Verify Luna Tauri chat trigger.
- Verify Stop preemption.
- Verify final report carries audit refs and no raw screenshot, OCR text, window
  title, contact name, clipboard value, or typed secret.
- Verify the Docker `_work` mount gate returns no output.

## Open Risks

1. PR5 per-tenant keys is still required before non-operator actuation.
2. `desktop_control_service.py` must be split before Slice 4 or any additional
   command/wrapper growth.
3. Canonical Python/Rust tables need a shared fixture to avoid drift.
4. Alpha CLI is currently installed locally but unauthenticated in this Codex
   environment; Luna Desktop remains the active review channel unless auth is
   explicitly restored.
5. The D3 PR body has a stale original table entry, but the correction comment
   and diff reflect the true non-API signing-boundary fix.
