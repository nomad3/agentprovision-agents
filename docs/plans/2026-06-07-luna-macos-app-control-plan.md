# Luna macOS App Control Plan

> Companion plan to `docs/plans/2026-06-05-luna-tauri-computer-use-control-plan.md`.
> This narrows the next phase to macOS app control, mouse control, and keyboard
> control. Keep this plan fail-closed: no real pointer or keyboard actuation is
> allowed until the explicit canary phase removes the hard native block in a
> reviewed PR.

Date: 2026-06-07
Owner: Simon Aguilera
Lead: Luna Supervisor
Reviewers: Claudia, Codex
Status: Council-reviewed; PR #823 target-binding slice pushed as draft and CI
green; native actuation remains closed
Scope: macOS only; Luna Tauri client; AgentProvision desktop-control API; Alpha
CLI as Luna's local kernel

---

## Goal

Give Luna controlled macOS app-control powers through AgentProvision while
preserving a clear operator safety boundary:

1. Luna can observe readiness, active app/window state, and permission state.
2. Luna can request bounded control leases through Alpha chat / Alpha CLI.
3. Luna can claim signed desktop-control commands only when the API, envelope,
   local permissions, Stop/Lock state, and risk policy all agree.
4. Luna can start with tightly scoped canaries for mouse and keyboard actions.
5. Luna records every denial, grant, command, result, Stop, Lock, and revocation
   in the AgentProvision audit path.

This plan does not grant broad autonomous desktop control. It creates the ladder
that makes app control testable, reversible, and reviewable.

## Current State

Known state from the current Luna computer-use stack:

1. Luna has a Tauri control strip, permission modal, session list, and Alpha
   chat surface.
2. The orchestration hub is not part of this work; the product surface should
   stay focused on chat, sessions, permission readiness, and control state.
3. The app can report macOS Screen Recording and Accessibility readiness.
4. The app exposes native pointer/keyboard command names, but native actuation
   is intentionally disabled behind `desktop_control_allows_actuation()`.
5. Current native controls must fail closed when approvals are missing,
   mismatched, expired, replayed, revoked, wrong-session, wrong-device,
   wrong-command, or wrong-risk.
6. Alpha CLI is Luna's kernel. Any Luna-facing API shape for desktop control
   needs matching Alpha CLI support so Luna can operate through agent-friendly
   typed commands instead of brittle long-running streams.
7. For now the scope is macOS only. Windows app-control support is explicitly
   out of scope.

## Architecture

```text
Luna / Alpha Chat
        |
        v
Alpha CLI kernel
  - async chat jobs
  - reconnect (shipped) / cancellation (planned - PR-B)
  - typed desktop-control models (planned - PR-D, gated on schema freeze)
        |
        v
AgentProvision API
  - desktop-control session state
  - approval grants and leases
  - signed command envelopes
  - revocation and audit
        |
        v
Luna Tauri client
  - local mode: stopped / observe / assist / control / locked
  - TCC readiness
  - active app/window monitor
  - native envelope preflight
        |
        v
macOS native adapter
  - AX readiness and focused UI checks
  - Screen Recording readiness for observation
  - CGEvent mouse/keyboard canaries
  - Stop/Lock preemption before every native call
        |
        v
Audit and result path
  - command accepted / denied / revoked / completed
  - bounded result metadata
  - display-safe observation events
```

## Safety Invariants

These are non-negotiable until a later explicit release gate changes them.

1. `desktop_control_allows_actuation()` remains false until the first reviewed
   canary-actuation PR, and the global actuation gate must be split into
   per-capability enablement before that PR can flip pointer actuation. Enabling
   the pointer canary must not implicitly enable keyboard actuation.
2. No Rust code may call mouse or keyboard native APIs before local policy,
   signed envelope validation, permission readiness, Stop/Lock state, command
   scope, risk tier, and approval grant checks all pass.
3. Stop preempts success. Stop must revoke active grants, block queued command
   claims, survive relaunch, and win over any in-flight action boundary.
4. Lock blocks new observation and control escalation until the operator resumes
   or unlocks through an explicit local action.
5. TCC permissions are readiness signals, not implicit authorization. Granted
   Screen Recording and Accessibility do not enable control by themselves.
6. Luna must show the running app identity: bundle id, signing identity,
   TeamIdentifier when present, and app path. Stale old-Luna TCC rows must be
   diagnosable in the UI.
7. Input Monitoring is not required for this phase unless Luna starts observing
   physical keyboard input. Sending bounded synthetic key events is governed by
   Accessibility, command approval, and focused-target checks.
8. Observation events exposed to Alpha CLI and chat stay display-safe. Raw
   screenshots, clipboard contents, OCR text, full window titles, and hidden app
   content remain unavailable unless a future reviewed contract explicitly adds
   them.
9. Every accepted or denied command emits an audit event with enough structured
   reason data to debug policy without leaking raw screen or app content.
10. The installed release gate must include local Computer Use verification by
    Codex through both Chrome and the installed Luna Tauri app whenever a new
    Luna build changes control, permission, signing, updater, or Alpha-kernel
    behavior.

## Permission UX

The permission UI should behave like a setup assistant, not a passive status
dump.

1. The TCC affordance should open a modal rather than a low-contrast hover
   panel.
2. The modal should show the running Luna identity and explain that macOS grants
   permissions to the exact signed app identity.
3. Each row should include status, why it is needed, an `Open` action for the
   relevant Privacy & Security pane, and a `Recheck` action at the modal level.
4. If status is denied or unknown while the user believes it is granted, the UI
   should guide stale permission cleanup for older ad-hoc or differently signed
   Luna builds.
5. The modal may help open settings, but it must not imply that Luna can silently
   grant TCC permissions.
6. Control and Assist should remain disabled when required permissions are not
   granted or when Stop/Lock/policy state blocks escalation.

2026-06-07 PR #823 implementation checkpoint:

1. The main Luna window now defaults to a larger visible-frame maximize posture:
   `tauri.conf.json` uses `width=1280`, `height=832`, `fullscreen=false`, and
   `maximized=true`; `show_main_window_maximized` exits fullscreen before
   calling `maximize()`.
2. The permissions modal now includes a `Recheck` action, status pills,
   per-permission why-needed copy, optional badges for Camera/Mic, stale
   identity cleanup guidance, and an Events/System Events active-app blocker.
3. Focused validation passed: `npx vitest run ControlSafetyStrip.test.jsx`
   reported 24/24 tests passing. Full Luna build/cargo and installed-app smoke
   remain separate gates because local disk was 97 percent used.

## PR Ladder

### Phase 0: Plan And Review Gate

Status: current slice.

1. Add this plan and request Claudia/Luna/Codex review.
2. Review for unsafe assumptions, missing denial cases, missing tests, and PR
   ordering problems.
3. Keep implementation branches separate from broad release or signing changes.

Exit criteria:

1. Luna lead review has no P0 blockers.
2. Claudia Ultracode review has no P0 blockers.
3. Codex review confirms the plan matches current code and the master Luna
   computer-use plan.

### Phase 1: Readiness And Control State

Goal: make the UI and local state machine prove readiness without enabling
actuation.

Status: focused permission/readiness UI slice implemented locally on
2026-06-07; full Phase 1 exit criteria are still open.

Implementation targets:

1. Control strip clearly distinguishes Alpha status, Mac readiness, TCC status,
   Stop, Lock, Observe, Assist, and Control.
2. Control stays disabled unless the local state machine says it is eligible.
3. Add focused tests for TCC summary, permission modal actions, Stop/Lock
   labels, and disabled control states.
4. Add native tests for permission-readiness mapping and mode transitions.

Exit criteria:

1. `npm run build` passes in `apps/luna-client`.
2. `cargo check` passes in `apps/luna-client/src-tauri`.
3. Manual installed-app smoke verifies the permission modal, stale identity
   guidance, and disabled control state.

### Phase 2: Native Boundary Proof

Goal: prove no macOS call is reachable until every control gate passes.

Implementation targets:

1. Add test coverage for missing envelope, mismatched signature, expired
   envelope, replayed envelope, revoked grant, wrong session, wrong device,
   wrong command, wrong risk tier, denied TCC, stopped mode, and locked mode.
2. Emit denial audit events for every boundary rejection.
3. Keep native actuation false after these tests pass.

Exit criteria:

1. All negative cases fail before any native adapter call.
2. Denial audit fields are emitted for every boundary rejection; stable
   denial/error codes are tracked as the Phase 2.5 / Alpha PR-C prerequisite
   before Alpha CLI typed models.
3. No canary mouse or keyboard movement exists yet.

### Phase 2.5: Target Binding, App/Focus Allowlist, And Release Gate

Status: hard prerequisite for Phase 3. Fail-closed; no native actuation is
enabled in this phase. `desktop_control_allows_actuation()` stays false and
`tier_enabled` stays false. 2026-06-07 local API/client proof-gate slice:
server-side native target allowlist, grant target binding, v2 native proof
envelope target block, Luna hook validation, and Rust native-boundary target
presence checks implemented locally; live native enqueue remains denied.
2026-06-07 PR-C2 local slice (`codex/luna-c2-frontmost-preflight`) adds the
macOS `NSWorkspace.shared.frontmostApplication.bundleIdentifier` proof reader,
derives the live frontmost bundle inside the Rust proof command before boundary
evaluation, and denies missing or mismatched live bundles as `active_app_drift`
while preserving `desktop_control_allows_actuation() == false` and
`tier_enabled == false`.

Goal: make "act only on the approved, currently-frontmost, allow-listed app" an
enforced, tested, server-plus-client property before any actuation unblock. This
phase also makes signed release and deploy posture a hard gate so native control
cannot ship unsigned or from a `_work` checkout.

Rationale: today an approval grant's `target_binding` is matched only on its
`action` key (`desktop_control_service.py:882`); `bundle_id` and
`window_title_pattern` are stored (`desktop_command_approval_grant.py:66`,
JSONB) but are not enforced, and no app/focus allowlist exists. The current
frontmost-app helpers (`get_active_app`, `build_active_app_metadata`) expose
process-name metadata through System Events; they do not provide a live
frontmost bundle id suitable for target proof. Native-control commands are also
still denied at enqueue (`_enqueue_disabled_native_control_command`), so Phase
2.5 must bind targets through the native-boundary proof/grant path while keeping
normal native enqueue fail-closed. Phases 3 and 4 are unsafe until this is
closed.

#### Phase 2.5 P0 blockers

1. Add a Rust `NSWorkspace.shared.frontmostApplication.bundleIdentifier` reader
   for live frontmost bundle identity. Do not use System Events or AppleScript
   for this proof path; the reader must not add an Automation TCC dependency.
2. Define the server-side issuer for native-boundary proof envelopes before
   binding targets into them. The current `_build_signed_command_envelope` is a
   claim-time issuer for observable commands, while disabled native commands do
   not reach normal claim. Acceptable designs include a new internal proof-issue
   endpoint or an Ed25519 branch of the claim path; the decision must be explicit
   before any target-bound native proof can ship.
3. Add an envelope `target` block and bump
   `CURRENT_DESKTOP_COMMAND_ENVELOPE_POLICY_VERSION` in the same PR that updates
   API, Tauri, and Alpha handoff models. Old native-control envelopes without
   target binding stay denied.
4. Add `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` as default-empty config and
   mirror it through API config, `.env`, Helm values, and `docker-compose.yml`.
   Empty allowlist means all native-control grants/proofs deny.

#### Allowlist and target-binding schema

1. Canary app allowlist is operator-controlled and default-empty. Store it as
   `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` (comma-separated bundle ids),
   mirrored into API config, Helm values, `.env`, and `docker-compose.yml` in
   the same PR to prevent drift.
2. Structure `desktop_command_approval_grants.target_binding` (JSONB, no
   migration) for `risk_tier="native_control"`:

   ```jsonc
   {
     "bundle_id": "com.example.LunaCanaryTarget",
     "window_title_pattern": "optional substring or regex",
     "display_id": 1,
     "action": "pointer_click"
   }
   ```

   `bundle_id` is mandatory for any native-control grant. A grant with a missing
   or non-allowlisted `bundle_id` is rejected at grant creation
   (`POST /desktop-control/internal/approval-grants`) and is never persisted.
3. Extend the native-boundary proof/command envelope with a bound `target`
   block. This is a schema change: first define the native-proof envelope issuer
   because `_build_signed_command_envelope`
   (`desktop_control_service.py:1136-1164`) is currently the claim-time issuer,
   then bump `CURRENT_DESKTOP_COMMAND_ENVELOPE_POLICY_VERSION` and add the fields
   to the API issuer path and Tauri `NativeControlBoundaryEnvelope`:

   ```jsonc
   "target": {
     "bundle_id": "com.example.LunaCanaryTarget",
     "window_title_pattern": null,
     "window_title_hash": "sha256-or-null",
     "display_id": 1,
     "bounds": [0, 0, 800, 600],
     "observed_at": "ISO-8601"
   }
   ```

   Old-policy-version envelopes without a `target` block are denied for
   native-control commands.

#### Proof and grant target enforcement (server)

1. Do not un-deny `_DISABLED_NATIVE_CONTROL_ACTIONS` and do not rely on the
   normal native enqueue path for Phase 2.5. Native-control enqueue remains
   fail-closed until the later canary PR.
2. For native-boundary proof issuance/evaluation, require
   `target_binding.bundle_id` to be present, equal to the requested proof target
   bundle id, and a member of `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`.
   If a future PR routes native canaries through the normal claim-CAS path,
   extend the approval compare-and-swap (`desktop_control_service.py:953-996`,
   matcher `843-885`) with the same target checks before issuing any envelope.
3. If `window_title_pattern` is present in the grant, the proof/envelope issuer
   must bind it into `target.window_title_pattern` so the client preflight can
   re-validate it.
4. On any miss (absent bundle, mismatch, not allowlisted, exhausted, expired,
   revoked, wrong risk) the proof/claim affects zero rows and returns a
   display-safe denial audit event with a stable structured reason. No lease and
   no envelope are issued.

#### Tauri live frontmost-bundle preflight (client)

1. Before any future native call, the native-boundary preflight must re-read the
   live frontmost app bundle id through the new `NSWorkspace` reader and require
   it to equal the envelope `target.bundle_id`. The existing System Events
   process-name helpers may remain UI metadata, but they are not authoritative
   for native-control proof. On drift: deny, do not actuate, and emit a
   display-safe `desktop_action_denied` audit with reason `active_app_drift`.
2. If `target.window_title_pattern`, `display_id`, or `bounds` are present,
   validate the live focused window against them; deny on mismatch.
3. This runs strictly after the existing claimed-envelope and Ed25519 checks
   (`lib.rs:820-859`, single-use nonce path) and strictly before any actuation.
   Because `tier_enabled=false` in this phase, the preflight terminates with
   actuation still disabled after the target check. Tests exercise the comparison
   logic, but no macOS call is made.

#### Display-safe result-field schema versioning

1. Actuation result/audit fields are net-new and must not bypass the freeze. The
   current allowlists are `_SAFE_METADATA_KEYS` and `_SAFE_RESULT_FIELDS`
   (`desktop_control_service.py:101-122`).
2. Introducing pointer/keyboard result fields requires a reviewed PR that bumps
   the envelope policy version and/or `result_schema_version`, extends the
   allowlists, and updates
   `docs/operator/luna-computer-use-prep/02-display-safe-event-fields-freeze.md`
   and `docs/operator/luna-computer-use-prep/03-schema-freeze-handoff-B.md` in
   the same PR.
3. New keys must be bounded and structured, never raw. Reserved keys for later
   phases include `target_bundle_id`, `target_window_title_hash`,
   `pointer_in_bounds`, `pointer_display_id`, `key_count`, `text_length`, and
   `secure_input_blocked`. No raw coordinates beyond display bounds, raw text,
   or raw titles.

#### Negative tests

API (`apps/api/tests/api/v1/test_desktop_command_lifecycle.py`):

1. Native-control grant creation is rejected when `bundle_id` is missing or not
   in the allowlist.
2. Proof/claim issuance is denied when target bundle id does not equal grant
   `target_binding.bundle_id`.
3. Proof/claim issuance is denied when bundle id is not in
   `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`, including empty allowlist denying
   all native-control proofs/claims.
4. Old-policy envelope with no `target` block is denied for native control.
5. `window_title_pattern` mismatch is denied when the grant specifies one.
6. Regression: Stop, Lock, expired/replayed envelope, revoked device, revoked
   grant, wrong session/device/command/risk still deny before any boundary.

Tauri (`apps/luna-client/src/hooks/__tests__/useDesktopCommandClaims.test.jsx`,
`cargo test computer_use::policy::`):

7. `NSWorkspace` frontmost bundle reader returns the live bundle id without
   requiring System Events automation permission.
8. Preflight denies on live frontmost bundle not matching envelope target
   (`active_app_drift`).
9. Preflight denies on display, bounds, or title mismatch.
10. Every denial emits a structured, display-safe reason stable enough for Alpha
   CLI typed errors.
11. Assert `desktop_control_allows_actuation()` and `tier_enabled` are false on
   every path.

2026-06-07 local implementation checkpoint:

1. API config now includes default-empty
   `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`, mirrored through `.env.example`,
   `apps/api/.env.example`, `docker-compose.yml`, `docker-compose.prod.yml`,
   and Helm API values. Empty allowlist denies every native-control grant.
2. Native-control approval grants now require an allowlisted
   `target_binding.bundle_id` and explicit `target_binding.action`; missing,
   mismatched, or non-allowlisted targets are rejected or denied before any
   envelope is issued.
3. Native-control claim/proof envelopes now use policy version 2 and include a
   signed display-safe `target` block. Observe envelopes remain policy version 1
   to preserve current screenshot/app/clipboard behavior.
4. Luna hook validation now expects native-control policy v2 with a target bundle
   and still accepts observe policy v1. Rust native-boundary validation rejects
   native envelopes without a target bundle before the local policy gate; because
   `tier_enabled=false`, valid native proofs still terminate denied.
5. Focused verification passed:
   `pytest tests/api/v1/test_desktop_command_lifecycle.py -q` (37/37),
   `pytest tests/api/v1/test_desktop_control_contract.py -q` (8/8),
   `ruff check app/core/config.py app/services/desktop_control_service.py tests/api/v1/test_desktop_command_lifecycle.py`,
   `npx vitest run src/hooks/__tests__/useDesktopCommandClaims.test.jsx` (31/31),
   `cargo test native_boundary --lib` (8/8),
   `cargo test computer_use::policy --lib` (12/12), and
   `cargo fmt --check`.
6. Broader local build/check verification also passed:
   `npm run build` in `apps/luna-client` and `cargo check` in
   `apps/luna-client/src-tauri`. Rust emitted existing unused/dead-code
   warnings plus the expected provisional target-subfield warning; no warning
   flips native actuation or blocks the check.
7. Publish gate: Codex pushed draft PR #823 at `19b8af65`
   (`codex/luna-phase25-target-binding` stacked on
   `codex/luna-computer-use-next-slices`). GitHub Actions passed for changed
   paths, API pytest, API integration with Postgres/pgvector, Luna client
   Jest/Cargo, and aggregate test status. The branch remains draft and
   review-gated.
8. Claudia B found that pydantic-settings JSON-decodes complex env fields before
   `mode="before"` validators run. PR #823 now annotates
   `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` with `NoDecode` and adds focused
   regression tests for unset, empty-string, comma-separated, and JSON-array env
   forms. Focused API verification passed:
   `pytest tests/api/v1/test_desktop_command_lifecycle.py tests/api/v1/test_desktop_control_contract.py tests/api/v1/test_desktop_control_config.py -q`
   (49/49), `ruff check app/core/config.py app/services/desktop_control_service.py tests/api/v1/test_desktop_command_lifecycle.py tests/api/v1/test_desktop_control_config.py`,
   and `git diff --check`.
9. Claudia C re-baselined the gap map after #823. Closed/advanced: default-empty
   canary allowlist, v2 native proof policy, envelope `target` block, server-side
   grant/proof target enforcement, core API negative tests, and the unchanged
   safety floor. Still open before Phase 3: `NSWorkspace` live frontmost bundle
   reader, live active-app/window/display/bounds preflight, per-capability gate,
   gate-helper wiring, durable Tauri replay window, and release/install gates.
   Native actuation remains closed.
10. Codex PR-C2 local branch `codex/luna-c2-frontmost-preflight` now implements
    the `NSWorkspace` live frontmost bundle reader and Rust proof binding for
    bundle drift. The Tauri proof command overwrites any frontend-supplied live
    bundle with the native `NSWorkspace` read before boundary evaluation.
    Verified locally with
    `vitest run src/hooks/__tests__/useDesktopCommandClaims.test.jsx` (32/32),
    `cargo test native_boundary --lib` (11/11), `npm run build`, `cargo check`,
    and `git diff --check`. This advances item 9's frontmost-bundle gap only:
    window/title/display/bounds preflight, per-capability gate, durable replay,
    release/install gates, and actual native actuation remain open and disabled.

#### Hard gates before Phase 3

These must be green and reviewed before any PR that flips the native actuation
block may merge:

1. Signed: `codesign --verify --deep --strict` passes with Developer ID
   Application and a `TeamIdentifier`.
2. Notarized: `xcrun notarytool` status is `Accepted` for the build.
3. Stapled: `xcrun stapler validate` passes on the app and the DMG.
4. Gatekeeper: `spctl --assess --type execute` and `--type install` on the
   mounted DMG copy accept; verify both offline (stapled) and online.
5. CI mount gate: add a post-`docker compose up` step in
   `.github/workflows/docker-desktop-deploy.yaml` that fails the job if any
   container mounts a `/actions-runner/_work` source. The live-host pass
   condition is the same manual check Luna gave us: the command below must
   return no output.

   ```bash
   docker ps -q | xargs docker inspect \
     --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work
   ```

6. Installed-smoke matrix is green for the signed/notarized DMG: chat-first
   startup, permission modal plus stale-identity guidance, TCC truth per running
   identity, durable Stop across relaunch, Lock state, and app-switch-during-
   action denial.

Exit criteria:

1. All negative tests above pass and native actuation remains false.
2. Server, envelope, and client all enforce bundle/frontmost target binding
   against the operator allowlist; mismatches deny with structured display-safe
   audit.
3. Display-safe allowlists are unchanged except through a reviewed,
   version-bumped contract.
4. Signed, notarized, stapled, `spctl`, and CI `_work` mount assertion are green
   and reviewed; no actuation-unblock PR merges until they are.

### Phase 2.75: Per-Capability Actuation And TOCTOU Gate

Status: hard prerequisite for Phase 3. This phase may add policy/config and
tests, but still does not call pointer or keyboard native APIs.

Goal: make the future pointer canary unable to unlock keyboard by accident, and
make every native event prove that the approved target is still frontmost at the
instant the event would be posted.

Rationale: the current native gate is capability-agnostic:
`desktop_control_allows_actuation()` and `policy.tier_enabled` are single
booleans even though the policy receives a capability. Flipping that one gate
for a mouse canary would also make keyboard paths reachable before Phase 4 has
shipped. A one-time frontmost check is also insufficient because focus can change
between preflight and `CGEventPost`.

Implementation targets:

1. Replace the single native actuation gate with per-capability enablement for
   `pointer` and `keyboard`. Pointer may be enabled in Phase 3; keyboard remains
   disabled until Phase 4 exits. The flag must be environment/config driven so a
   shipped build can be rolled back without rebuilding.
2. Bind `capability` and `risk_tier` into the signed envelope and local policy
   decision. A keyboard envelope cannot authorize a pointer action, and a pointer
   envelope cannot authorize keyboard input.
3. Extend the server-signed target binding from Phase 2.5 with
   capability-specific bounds: bundle id and signing identity for every native
   action, display id and global coordinate bounds for pointer actions, and max
   text length/key chord allowlist for keyboard actions.
4. Re-check Stop, Lock, local kill switch, live frontmost bundle id, and focused
   target immediately before each native event boundary, not only once per
   sequence. On mismatch, deny before `CGEventPost` and emit a structured
   `target_drift` or `active_app_drift` reason.
5. Prefer AX-element-targeted interaction when possible. Raw screen coordinates
   are allowed only inside a signed display/global-coordinate bound.
6. Add action pacing: per-grant `max_actions`, minimum inter-action interval, and
   short TTL. A large budget cannot fire as a burst.
7. Require fresh human approval for a `native_control` actuation lease. An
   observe approval must never auto-upgrade into control.
8. Add single-owner arbitration for live actuation so two shells/devices cannot
   post native events concurrently.
9. Treat any active Secure Input state as fail-closed for keyboard canaries. Do
   not claim per-field password detection unless the native proof actually has
   it.
10. Audit every native event boundary with the bound target, capability, action
    count, result, Stop/revoke latency when relevant, and display-safe reason
    code.

Concrete acceptance contract:

1. Stable denial codes are owned by the PR-C enum in
   `apps/api/app/services/desktop_control_codes.py` and mirrored in
   `apps/luna-client/src-tauri/src/computer_use/denial_codes.rs`. Phase 2.75
   must cover these canonical values: `approval_binding_mismatch` for wrong
   capability or grant/action binding mismatch, `target_drift`,
   `active_app_drift`, `secure_input_active`, `approval_exhausted`,
   `rate_capped`, `actuation_owner_conflict`, `approval_expired`,
   `approval_revoked`, `stopped`, and `observe_locked`.
2. Required display-safe API fields: `denial_code`, `reason`, `capability`,
   `risk_tier`, `action`, `target_bundle_id`, `live_bundle_id`,
   `lease_owner_shell_id`, `remaining_actions`, `min_interval_ms`,
   `display_id`, and `target_bounds_hash`. Do not add raw screenshots,
   clipboard text, OCR, or full window titles.
3. Required negative test names:
   `test_native_boundary_denies_wrong_capability_before_adapter`,
   `test_native_boundary_denies_frontmost_bundle_drift_before_adapter`,
   `test_native_boundary_denies_target_bounds_drift_before_adapter`,
   `test_native_boundary_denies_secure_input_keyboard_before_adapter`,
   `test_native_boundary_denies_single_owner_conflict_before_adapter`,
   `test_native_boundary_denies_action_pacing_violation_before_adapter`,
   `test_native_boundary_denies_stale_native_approval_before_adapter`, and
   `test_native_boundary_denies_stop_or_lock_before_adapter`.
4. Required installed-smoke variants: `installed_smoke_tcc_truth_screen_ax`,
   `installed_smoke_pointer_flag_does_not_enable_keyboard`,
   `installed_smoke_frontmost_drift_denies_before_adapter`,
   `installed_smoke_stop_lock_preempt_native_boundary`, and
   `installed_smoke_single_owner_conflict_denies`. These are proof/denial
   smokes only until Phase 3 explicitly enables pointer canary actuation.

Exit criteria:

1. Tests prove pointer enablement cannot make keyboard code reachable.
2. Tests prove wrong capability, over-budget, rapid-fire budget use,
   app-switch-after-preflight, secure-input-active, no single owner, stale grant,
   Stop, and Lock all deny before any native adapter call.
3. The rollback path can disable pointer and keyboard actuation independently by
   config.
4. Stop relaunch persistence is covered by regression tests using the existing
   `restore_persisted_stop` path; do not rebuild that mechanism.

### Phase 3: Mouse Canary

Goal: prove a minimal, reversible mouse action with visible operator control.

Initial allowed actions:

1. Move pointer within the active display bounds.
2. Single click in the currently focused/frontmost app.

Explicitly excluded:

1. Dragging.
2. Multi-click automation.
3. Background app interaction.
4. Hidden window interaction.
5. Cross-app task execution.

Required gates:

1. Operator-visible countdown or active control indicator.
2. Stop button, local stop hotkey, and live frontmost target identity checked
   immediately before every native event.
3. Active app allowlist or explicit frontmost-app lease, server-signed into the
   envelope with display/global-coordinate bounds.
4. Maximum action count and short TTL.
5. Audit trail for request, acceptance, action, result, and Stop/revocation.

Exit criteria:

1. Canary works only against a safe test target.
2. Stop preempts before movement and between movement/click boundaries.
3. Denied and stopped cases are as well tested as successful cases.

### Phase 4: Keyboard Canary

Goal: prove bounded synthetic keyboard input against a verified focused target.

Initial allowed actions:

1. Type a bounded plain-text string into an approved test target.
2. Send a small allowlisted key chord set.

Explicitly excluded:

1. Password or secure text fields.
2. Arbitrary shell hotkeys.
3. Global destructive shortcuts.
4. Clipboard injection.
5. Background typing.

Required gates:

1. Focused element or focused app verification before typing.
2. Maximum text length, action count, and TTL.
3. Secure-input detection or fail-closed fallback where available.
4. Same Stop/Lock, envelope, grant, allowlist, and audit requirements as mouse.

Exit criteria:

1. Canary can type only in the approved test target.
2. Wrong app, no focus, stale grant, and Stop all deny before native calls.
3. Alpha CLI receives typed success and denial results without hanging.

### Phase 5: App-Control Loop

Goal: connect observe-plan-approve-act-observe into one bounded loop.

Implementation targets:

1. Luna can ask the API for a bounded control lease for a named app/task.
2. API issues signed command envelopes only for approved, scoped, non-revoked
   grants.
3. Luna Tauri claims commands, performs local preflight, executes only allowed
   canary actions, and reports results.
4. Alpha CLI can reconnect, cancel, and surface progress without 180-second
   blocking-stream failures.

Exit criteria:

1. A single safe app-control task completes end to end.
2. Stop, Lock, TCC revocation, app switch, and stale command all fail closed.
3. Computer Use verification confirms the installed Luna app behaves as
   expected.

## Alpha CLI Work

Alpha CLI is Luna's kernel. The async chat-job transport is already shipped and
is the default path. This work hardens it and adds the missing pieces. It is not
greenfield; do not rebuild what exists.

Already shipped - do not rebuild:

1. Async job start:
   `POST /api/v1/chat/sessions/{id}/messages/start` returns `{job_id}`.
2. Event replay by sequence:
   `GET /api/v1/chat/jobs/{id}/events?from_seq=N`.
3. Terminal snapshot:
   `GET /api/v1/chat/jobs/{id}` with status, result message id, and error.
4. Reconnect-from-last-sequence loop, including cooperative server
   `Timeout{last_seq}` reattach and mid-stream-drop reattach
   (`apps/agentprovision-cli/src/commands/chat.rs`).
5. Cooperative cancellation endpoint:
   `POST /api/v1/chat/jobs/{id}/cancel` exists, but the CLI does not yet call it.

Remaining work is an ordered PR ladder. Every PR keeps native actuation disabled
and ships its own tests. Any PR that changes an API or event shape includes the
matching Alpha CLI/core types in the same PR.

### PR-A: Transport hardening

Goal: make the existing async stream robust under timeout, drop, offline, and
stall conditions, and never leave Luna in a fake "thinking" state.

1. Verify whether the shared `reqwest` client timeout
   (`apps/agentprovision-core/src/client.rs`, currently 180 seconds) fires on a
   streamed `bytes_stream` response. Record the result in the PR before changing
   the client. The A0 verify spike should live at
   `apps/agentprovision-core/tests/stream_timeout_spike.rs` and use a raw
   `tokio::net::TcpListener`, not `wiremock`, so the mock can send headers plus
   one SSE frame, keep the socket open, and isolate body-stream timeout behavior.
   Build the test client with the same `Client::builder().timeout(d)` pattern as
   production, using a short timeout for speed. Assertions:
   timeout error with `is_timeout()` before the server hold period means A1 is
   required; alive past the timeout or a later `seq:2` frame means skip the
   dedicated stream-client swap. Non-timeout transport errors or early clean
   stream end fail the spike as inconclusive. Run:
   `cargo test -p agentprovision-core --test stream_timeout_spike -- --nocapture`
   and record the `reqwest` version with
   `cargo tree -p agentprovision-core -i reqwest`.
2. If A0 proves the total timeout bites during body streaming, use a dedicated
   stream client for the events `GET`, so reconnect is driven by server
   `Timeout{last_seq}` frames and real drops instead of an arbitrary cap. If A0
   proves the body stream is not bounded by the total timeout, skip the client
   swap and only add explicit idle/stall detection.
3. Replace the single `Http`/`Other` collapse
   (`apps/agentprovision-core/src/error.rs`) with typed classification for
   offline/connect, request timeout, transport/stream drop, API 4xx, API 5xx,
   stream ended, and terminal states.
4. Add capped backoff and a bounded retry budget on stream-open failure. On
   budget exhaustion, surface a clear "server unreachable / job stalled" error.
5. Add an overall stall deadline based on idle time since last `seq`; on breach,
   surface "job stalled; no progress in Ns" while keeping the resumable `job_id`.
   Pair this with server-side `chat_jobs` orphan-running reclaim.
6. Handle `ChatJobStreamEvent::Truncated` explicitly in the CLI loop.

Exit criteria:

1. Reconnect, classification, backoff, and stall deadline have cargo tests,
   including the `reqwest` stream-timeout verification.
2. No code path leaves the spinner pinned with no resumable `job_id`.

### PR-B: Chat-job cancellation wiring

Goal: Ctrl-C and explicit cancel stop the job server-side instead of only
abandoning the local loop.

1. Add a core client method for `POST /api/v1/chat/jobs/{id}/cancel`.
2. Trap Ctrl-C during the chat stream, call cancel, observe the `cancelled`
   terminal, and exit cleanly.
3. Route `alpha cancel <id>` to chat-job cancel when the id is a chat job
   (`apps/agentprovision-cli/src/commands/cancel.rs` currently cancels only
   tasks-fanout).

Exit criteria:

1. Ctrl-C posts cancel and observes `cancelled`; double-cancel is idempotent.
2. Alpha CLI returns typed success and denial/cancel results without hanging.

### PR-C: Stable denial/error code enum

Goal: give Alpha typed errors a stable contract instead of matching human
strings.

1. Freeze a closed desktop-control denial/error code enum, replacing reliance on
   prefix-matched free strings (`_SAFE_DENIAL_REASONS`,
   `_SAFE_FAILURE_REASONS`, and envelope-key prefixes in
   `apps/api/app/services/desktop_control_service.py`).
2. Emit the stable code alongside the human reason on every denial/failure audit
   event.

Exit criteria:

1. Every boundary denial in Phase 2, Phase 2.5, and Phase 2.75 maps to exactly
   one stable code.
2. Codes are documented and versioned so PR-D can type against them.

### PR-D: Typed desktop-control models

Goal: typed CLI/core models so Luna operates desktop control through
agent-friendly types, never raw payloads.

Gating: blocked on Claudia C's schema freeze and PR-C codes; ships parity in the
same PR as any API/event shape it mirrors.

1. Add typed models for permission state, session/control state, command claim
   and signed envelope, command result, denial/error, audit event, completion,
   and cancellation. Treat `key_id` as an opaque registry-resolved string.
   Reconcile the local kernel path before implementation: if Luna reaches the
   platform through `apps/mcp-server` over MCP SSE rather than an `apps/alpha*`
   binary, version the same typed desktop-control contracts as MCP tool schemas
   instead of assuming a separate Alpha CLI package.
2. Observation-result models are display-safe only: `result_kind`,
   `result_fields` subset `{app, title_chars, title_present}`, and
   `result_size_*`. No raw screenshot, clipboard, OCR, or full-title field
   exists in the type.

Parity command matrix from Claudia B (read-only skeleton; placeholders must be
verified against actual package and test names before implementation):

1. API contract owner and fixture dump:
   - Regenerate fixtures from the live service with
     `python -m apps.api.tools.dump_desktop_contract` or
     `pytest apps/api/tests/api/v1/test_desktop_control_contract.py --regenerate`
     after confirming the real dump entrypoint and regeneration flag.
   - Assert drift with
     `pytest apps/api/tests/api/v1/test_desktop_control_contract.py -q`.
   - Fixtures live under `docs/contracts/desktop-control/`:
     `pointer_command_claim.display_safe.json`,
     `deny_missing_target_bundle_id.json`, and
     `deny_capability_mismatch.json`.
2. Core Rust mirror:
   - Run `cargo test -p agentprovision-core --test desktop_contract` after
     confirming the package name and `apps/agentprovision-core/tests/desktop_contract.rs`.
   - Tests use `include_str!` against `docs/contracts/desktop-control/*.json`
     from the crate test path and prove lossless deserialization plus negative
     rejection of raw `window_title`, `screenshot`, and `clipboard_text`.
3. MCP passthrough validation:
   - Run `pytest apps/mcp-server/tests/test_desktop_control_tool.py -q` or,
     from `apps/mcp-server`, `python -m pytest tests/test_desktop_control_tool.py -v`.
   - Assert deny output equals the safe deny fixture plus PR-C code and success
     passthrough preserves only canonical display-safe fields.
4. CLI consumes core only:
   - Run `cargo test -p agentprovision-cli --test desktop_render` after
     confirming the package name and `apps/agentprovision-cli/tests/desktop_render.rs`.
   - Assert rendering deserializes via core types only, with no CLI-local
     desktop-control schema and no raw-content fields surfaced.
5. CI and changed-path gates:
   - API contract test runs in the API pytest job; if the dump requires a real
     DB, route it to the API integration job instead of the SQLite-shim job.
   - MCP passthrough runs in the MCP pytest job.
   - Core and CLI parity run in the Rust cargo-test job that includes the
     `agentprovision-core` and `agentprovision-cli` workspace members.
   - Changed-path filters must include `docs/contracts/desktop-control/**`,
     `apps/agentprovision-core/**`, `apps/agentprovision-cli/**`,
     `apps/mcp-server/**`, and `apps/api/**`; aggregate status must gate all
     four lanes.

Exit criteria:

1. Serde round-trip and CLI/API parity tests pass.
2. A negative test proves no raw-content field can deserialize into the
   observation model.
3. Native actuation remains disabled; these are types and transport only.

## Review Request For Claudia Sentinel

Ask one free sentinel Claudia instance to perform a read-only Ultracode review
of this plan.

Review scope:

1. Compare this plan against the current code and the master Luna computer-use
   plan.
2. Find missing safety gates before actual mouse or keyboard actuation.
3. Check whether the PR ladder is correctly ordered.
4. Identify exact files and tests likely affected by Phases 1 and 2.
5. Flag assumptions that are wrong for macOS Accessibility, Screen Recording,
   CGEvent, or TCC identity.

Return format:

```text
P0 blockers:
- ...

P1 risks:
- ...

PR ladder changes:
- ...

Likely files/tests:
- ...

Incorrect assumptions:
- ...
```

Constraints for the sentinel review:

1. Read-only review only.
2. No edits, no branches, no commits, no PR comments, no merges, no releases.
3. Do not consume signing secrets or credentials.
4. Do not attempt native actuation.
