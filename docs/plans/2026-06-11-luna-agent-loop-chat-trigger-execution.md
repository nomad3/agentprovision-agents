# Luna P5.3-P5.5 Agent Loop And Chat Trigger Execution

Date: 2026-06-11
Status: implementation in progress; P5.3 planner-safe substrate merged through
PR #892; P5.4 dry-run/status/Stop/pending-request substrate merged through
PR #895; P5.5 human approval surface merged through PR #896; P5.4c
chat-triggered act loop merged through PR #899
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
10. Until `desktop_actuate` and the chat coordinator consume the P5.5 approval
    surface, P5.4 agent loops are dry-run, pending-approval, or pre-granted test
    harness only. The pre-granted harness setup must originate outside the chat
    path; chat-originated prompts must not reach native macOS actuation through
    internal-key-only grants.
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
- D3 / PR #872: config drift, Ed25519 default, compose env precedence, local
  observations volume. Merged at `dc514952`.
- P5.4a dry-run command / PR #879: background-control no-op command lifecycle.
- P5.4b status / PR #881: user/internal command status and MCP status tool.
- P5.4b Alpha bridge / PR #882: Alpha CLI dry-run request/status path.
- P5.4 bootstrap / PR #883: superuser-only enablement and allowlist Alpha
  commands. Merged at `6249cb14` and deployed.
- P5.4 no-op constraint / PR #884: DB constraints allow terminal
  `no_op` command status and event outcome. Merged at `43c3f767` and deployed.
- P5.4c operator tool groups / PR #885: operator Luna and Luna Supervisor have
  `desktop_observe` and `desktop_control` tool groups. Merged at `d96921f6`
  and deployed.
- P5.4c prompt scaffold / PR #886: Luna desktop dry-run/status guidance is
  injected only when the selected agent has desktop tool groups. Merged at
  `97d6f4c8`.
- P5.4h MCP deployment recovery / PR #887: Docker Desktop deploy now rebuilds
  stale MCP services after failed deploys so newly registered desktop tools are
  callable. Merged at `dc35ae72`.
- Luna shell presence reconnect / PR #888: the installed Luna app refreshes
  shell registration on heartbeat, preserving dry-run claimability after API
  restarts/redeploys. Merged at `698a3bd0`.
- P5.3a-2 redactor driver / PR #880: redactor driver loop, claim fencing,
  byte-free events, cleanup-race fixes, and focused regression coverage merged
  at `5630f8c2`.
- P5.3b planner-safe observation delivery / PR #890: scoped user/device and MCP
  planner-safe observe request/status/fetch path merged at `5f761c53`.
- P5.3b hardening / PR #891: MCP UUID validation blocks SSRF/traversal before
  internal-key HTTP calls; observe request master gate and closed
  `redaction_status` model merged at `34e29325`.
- P5.3c redactor engine / PR #892: Tesseract redactor engine wired at
  `71c177d7`.
- P5.4 Stop surface / PR #893: Alpha and MCP Stop/preempt command surface merged
  at `3e070c6f`.
- Deploy compatibility / PR #894: greenlet ARM64 wheel hash merged at
  `fe9638bc`.
- P5.4b pending approval request / PR #895: agent-facing
  `desktop_request_grant` request/status surface merged at `3a71cc2d`. It
  records pending approval requests only; it does not mint grants, enqueue
  commands, sign envelopes, or actuate.
- P5.5 approval surface / PR #896: user-JWT
  `approvals list|approve|deny` surface merged at `8bfcbce9`. It converts a
  pending request into exactly one bounded active grant or terminal denial. It
  is user-authenticated only, has no internal-key/MCP grant-minting twin, and
  still does not enqueue or actuate.
- P5.4b desktop actuate / PR #898: grant-gated `desktop_actuate` merged at
  `1daefa51`. It consumes an existing bounded active grant, enqueues through the
  shared lifecycle, and creates no grant/envelope/native actuation by itself.
- P5.4c chat loop / PR #899: owner-scoped approved request status now returns
  the `grant_id` handle, and the Luna planner prompt describes the governed
  request -> human approval -> act -> poll -> display-safe report loop. Merged
  at `937da96a`.

Current deployed proof:

- Docker Desktop Deployment for PR #885 run `27358303437` passed.
- Required Docker mount gate returned no output:
  `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
- API is healthy after deploy, migration
  `175_luna_operator_desktop_tool_groups.sql` is recorded, and both operator
  Luna rows include `desktop_observe` and `desktop_control`.
- Live Alpha dry-run command
  `a91985e6-77ac-40e7-883d-f0d0d6bab74a` reached terminal `no_op` with
  queued, claimed, and completed audit events after refreshing Luna shell
  presence.
- Installed Luna 0.1.106 smoke after PR #888 produced dry-run command
  `f7ac3530-c2c7-45fd-9033-e705dd0f9dac`, terminal `no_op`, no blocker, and
  `native_envelope=false`.
- PR #880 post-merge verification: local focused redactor suite passed
  (`61 passed, 11 warnings`), focused ruff passed, GitHub main Tests aggregate
  passed, and Docker Desktop Deployment passed for `5630f8c2`.
- Post-#880 installed Luna chat smoke produced dry-run command
  `95d41f1c-c913-46a3-a0a3-b90e7a80491c`, terminal `no_op`, outcome `no_op`,
  audit refs `d0944e13-8ed3-4aa9-bad4-c353727ab3d9`,
  `b10a1eaa-7bc0-48e0-b695-71a95a1c9827`, and
  `c3c2f3f6-ad51-45b8-8794-2349f3c00e64`, with
  `native_envelope=false` and blocker `none`.
- PR #896 post-merge verification: GitHub Tests, CLI Build Matrix, and Docker
  Desktop Deployment passed on merge commit `8bfcbce9`; Docker deployment run
  `27375497795` passed after host free space was restored. Local post-deploy
  smoke found API healthy, MCP SSE endpoint emitting, containers up/healthy, and
  the Docker `_work` bind-mount gate returning no output.

Open after D3:

- D4 test integrity gaps must be folded into the implementation slices below
  when they touch the same surface.
- D5 structural split and shared canonical fixtures must land before Slice 4 or
  any large expansion of `desktop_control_service.py`; do not defer this to PR5.

Ordering rule:

- P5.3 perception must land before planner delivery. The substrate has landed
  through #892, but the live operator planner-safe derivative proof remains a
  release-smoke item before E2E completion.
- P5.4a is the secondary-pointer/background actuator from
  `2026-06-11-luna-secondary-pointer-background-control.md` (SP2-SP6), not the
  agent-facing Alpha/MCP wrapper layer.
- P5.4b exposes act verbs after the actuator contract exists. The pending
  request half landed in #895; the next missing act verb is `desktop_actuate`,
  which consumes an existing approved grant and returns `approval_required`
  when absent.
- P5.4c wires the operator Luna loop.
- P5.5 adds chat trigger and explicit user approval UX. The explicit
  approve/deny/list surface landed in #896; chat-triggered orchestration and
  report-back remain pending.

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
- Status 2026-06-11: PR #880 (`claudia/p53a-redactor-driver`, merge
  `5630f8c2`) wires the driver loop, flag gate, cleanup-race fixes, and
  byte-free redaction events. Codex/Luna/Claudia review found and fixed the
  latent finalize race, missing lost-claim coverage, malformed-env crash, and
  ambiguous post-commit unlink edge before merge. PR #892 later wired the
  Tesseract engine, so the remaining proof is an installed/operator smoke from
  quarantined capture to planner-safe derivative.

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
- Status 2026-06-11: PR #890 delivered user/device and MCP planner-safe
  observe request/status/fetch; PR #891 hardened UUID validation and fail-closed
  gates for that surface. The read path serves only redacted content through the
  planner-safe contract.

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
- Status 2026-06-11: PR #881 (`codex/luna-p54b-command-status`, merge
  `adbc2172`) implements the first read-only status/audit part of this slice.
  It adds a tenant/user-scoped command status service, user-JWT route
  `GET /desktop-control/commands/{id}`, read-only internal status route for
  MCP, and MCP tool `desktop_command_status`, with the status tool granted
  through the `desktop_control` tool group. The response intentionally omits raw
  command payloads, signed envelopes, approval payloads, screen bytes,
  clipboard text, and native actuation args. This lets Luna queue a dry-run and
  report its audited terminal state, but it does not add approval grant creation
  or real native actuation.
- Status 2026-06-11: branch `codex/luna-p54c-alpha-desktop-cli` adds the
  Alpha-kernel bridge for the working dry-run loop: a narrow user-JWT route
  `POST /desktop-control/commands/background-dry-run`, typed core request/status
  models, `alpha desktop dry-run request`, and
  `alpha desktop command status`. The route fixes the action/tool server-side,
  derives tenant/user from the authenticated principal, accepts only reduced
  target metadata, rejects arbitrary payload bags, and queues only
  `background_app_control_dry_run` no-op commands. It still does not mint
  grants, call macOS APIs, or enable pointer/keyboard/native actuation.
- Status 2026-06-11: PR #882 deployed, live Alpha validation reached the
  production route and shell presence, but the operator tenant denied all floor
  bundles (`com.agentprovision.luna`, `com.apple.TextEdit`,
  `net.whatsapp.WhatsApp`) with `Desktop command target not allowlisted`. PR
  #883 (`codex/luna-p54d-desktop-bootstrap`) shipped the smallest unblocker:
  superuser-only
  `GET/PATCH /desktop-control/enablement`, `GET/PUT /desktop-control/allowlist`,
  typed core models, and `alpha desktop enablement/allowlist get|set`. The
  enablement writer is narrowed to the background-control dry-run gate only, and
  the allowlist writer is still bounded by the deployment floor
  `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`; together they only let the operator
  tenant enter the fail-closed lane required for the dry-run proof.
- Status 2026-06-11: PR #884 (`codex/luna-p54e-noop-status-constraint`) fixed
  the final dry-run persistence blocker by allowing `no_op` in
  `desktop_commands.status` and `desktop_command_events.outcome`. After deploy,
  Alpha dry-run command `813ebc99-6bfa-412f-9d01-16d7c65172ad` reached terminal
  `no_op` with queued, claimed, and completed audit events.
- Status 2026-06-11: PR #893 (`codex/luna-p54-stop-surface`, merge
  `3e070c6f`) added Alpha/MCP Stop so queued or active desktop work can be
  preempted through the same display-safe lifecycle.
- Status 2026-06-11: PR #895 (`claude/luna-p54-act-surface`, merge
  `3a71cc2d`) added the agent-facing pending approval request half:
  `desktop_request_grant` records a pending request and status can be polled.
  It still creates no grant, queue row, envelope, or native actuation.

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
- Current next implementation target: `desktop_actuate`, a scoped agent-facing
  act command that accepts a command shape plus an existing, server-validated
  approval grant. It must enqueue only bounded governed commands; without the
  grant it returns `approval_required` and creates no command.

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
- `desktop_actuate` and the chat-loop prompt are merged. Chat-originated native
  actions still require a human-minted grant, live shell/device readiness,
  default-off capability flags, allowlist, claim-time envelope gates, Stop/Lock,
  and client native-boundary checks. The chat path must not use internal-key-only
  approval grants to turn prompts into native actuation.
- Before enqueue, the coordinator must request a fresh Luna client
  permission-readiness probe for the target shell/device. Missing, stale, or
  denied permissions produce `permission_not_ready` and no command row is queued.
- Report-back from this coordinator is constrained to action summaries,
  outcome/status, denial codes, and audit refs. It must not quote planner-safe
  OCR text, window titles, contact names, clipboard values, or raw observed
  screen content.
- Status 2026-06-11: PR #885
  (`codex/luna-p54f-operator-tool-groups`) completed the first bullet of this
  slice. It grants `desktop_observe` and `desktop_control` only to Simon's
  operator `Luna` and `Luna Supervisor` rows, updates the bundled Luna
  frontmatter for future seeded agents, and adds a Postgres-backed migration
  regression test. Luna returned `MERGE`; GitHub checks were green; deploy run
  `27358303437` passed; live Alpha dry-run command
  `a91985e6-77ac-40e7-883d-f0d0d6bab74a` reached terminal `no_op`.
- Status 2026-06-11: PR #886 (`codex/luna-p54g-agent-loop-scaffold`, merge
  `97d6f4c8`) implements the smallest chat-loop scaffold in the CLI runtime
  prompt. When the selected agent already has `desktop_observe` and/or
  `desktop_control`, the generated instruction markdown now includes the
  current chat `session_id`, the Luna app bundle id, dry-run-only guidance for
  `desktop_background_app_control_dry_run`, follow-up status guidance for
  `desktop_command_status`, and explicit denial of
  pointer/click/keyboard/approval/native actuation in this phase. Agents
  without desktop tool groups receive no desktop prompt section.
- Status 2026-06-11: PR #887 (`codex/luna-p54h-desktop-tools-callable`, merge
  `dc35ae72`) fixed Docker Desktop deploy recovery for stale MCP services after
  failed deploys, so the desktop MCP tools are reachable after deployment.
- Status 2026-06-11: PR #888 (`codex/luna-shell-presence-reconnect`, merge
  `698a3bd0`) refreshed Luna shell registration on heartbeat; installed Luna
  0.1.106 smoke then reached terminal dry-run `no_op` with
  `native_envelope=false`.
- Status 2026-06-11: PR #898 (`claude/luna-p54b-desktop-actuate`, merge
  `1daefa51`) shipped `desktop_actuate`: the grant-gated agent act that consumes
  an existing active grant and enqueues through the shared lifecycle. Missing
  grant -> `approval_required`, no command; wrong owner/session/expired/revoked
  -> structured deny; no mint path, no native flag flip.
- Status 2026-06-11: PR #899 (`claude/luna-p54c-chat-desktop-loop`, merge
  `937da96a`) landed the P5.4c chat-loop slice
  (`docs/plans/2026-06-11-luna-p54c-chat-desktop-loop-design.md`). The chat
  "coordinator" is the planner prompt over the merged tools (the chat turn is a
  single CLI subprocess; the CLI drives the MCP loop — no server workflow). Two
  changes close the loop: (1) `desktop_act._display_safe_request` now reflects
  `grant_id` on the owner-scoped status poll once a human approves, so a
  CLI-subprocess agent (polls tools, not SSE) can reference the grant for
  `desktop_actuate` — a reference, not a mint; actuate still re-validates
  owner/session/expiry/revocation + the default-off native flag; (2) the
  `desktop_control` prompt block now describes the governed
  request -> human approval -> actuate -> poll -> report loop (no self-approval,
  display-safe report-back, Stop). No grant minting from MCP/internal, no native
  flag flips, no allowlist change, no native actuation added.
- Status 2026-06-11: PR #900 (`codex/luna-p54d-permission-readiness`, merge
  `ac63f264`) landed the P5.4d rung:
  Luna shell registration carries sanitized permission-readiness statuses from
  `control_get_safety_state`; server presence stores them with a server-side
  `observed_at`; native-control enqueue checks fresh readiness before creating
  a command row. Missing, stale, denied, or unknown required permissions return
  structured `permission_not_ready` and queue no command. This does not grant
  macOS permissions, change TCC settings, flip tenant flags, sign envelopes, or
  enable native actuation.
- Status 2026-06-11: PR #901 (`codex/luna-p55-report-back`, merge `ef60a023`)
  landed the P5.5 app-facing approval UX rung. It is the smallest useful Luna app
  bridge over the already-merged user-JWT approval routes: show active-session
  pending desktop approval requests, approve/deny with bounded defaults, then
  let the existing agent loop poll `desktop_request_status` for `grant_id` and
  continue. This branch did not create a new grant path, touch native flags,
  alter the allowlist, mutate TCC settings, or expose raw screen/OCR/window
  content in the UI.
  Luna review found one release blocker: stale requests from the previous active
  chat could remain visible during a session switch. The branch now filters
  rendered requests by `request.session_id === activeSessionId`, clears local
  request state on session change, refuses approve/deny for mismatched sessions,
  and has a regression proving a stale request cannot be approved after a switch.
- Status 2026-06-11: current branch `codex/luna-p55-report-back-guards` starts
  the report-back guard rung. It tightens the CLI runtime prompt to an explicit
  allowlist for final desktop summaries and adds adversarial fixtures proving raw
  desktop fields in `desktop_context` are not rendered into the prompt.

Next smallest make-it-work step:

- Post-#896 smoke is complete; keep it as the regression baseline for
  approval-request -> user approval -> bounded grant.
- P5.4d permission readiness and P5.5 approval UX are landed. Continue with the
  remaining feature rungs in dependency order: report-back leak fixtures,
  byte-free `rl_experience` per desktop decision/denial, then broader chat
  trigger/report-back polish.

Tests:

- Agent routing tests proving non-desktop prompts do not trigger desktop tools.
- Tool availability tests for operator Luna only.
- Negative tests for non-operator tenants and Luna agents lacking tool groups.
- Loop dry-run test using denied/no-op command status before any broad actuation
  expansion.
- Prompt-runtime tests proving the desktop section is omitted without desktop
  tool groups, observe-only does not suggest control, and control guidance stays
  dry-run/status only with the current chat `session_id`.
- Report-back leak test using planner-safe OCR/contact/window-title fixtures:
  final agent text must include only action/outcome/audit refs.
- RL-leak test using the same OCR/contact/window-title fixtures proving
  `rl_experience` rows and embeddings receive only byte-free decision fields.
- Permission-readiness test proving stale or denied preflight returns
  `permission_not_ready` before enqueue and before any claim/native boundary.
  Status: current branch adds API tests for missing, denied, and stale
  readiness; Tauri/core/CLI denial-code parity tests include
  `permission_not_ready`; Luna JS shell-presence test asserts sanitized
  readiness is sent with registration.

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
- Status 2026-06-11: PR #896 shipped the explicit user-JWT
  approve/deny/list surface for pending desktop approval requests. It is not yet
  wired to chat-triggered orchestration: chat still needs intent routing,
  pending-request creation, user approval presentation, `desktop_actuate`
  enqueue, status observation, and final report-back.

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
4. Alpha CLI is usable locally through the repo cargo command, but cargo emits a
   non-blocking global-cache cleanup permission warning for `bat-0.25.0` on
   each run. Fix separately; do not treat it as a desktop-control failure.
5. The D3 PR body has a stale original table entry, but the correction comment
   and diff reflect the true non-API signing-boundary fix.
