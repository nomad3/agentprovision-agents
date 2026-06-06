# Luna Tauri Computer Use Control Plan

> For agentic workers: implement this plan phase-by-phase using checkbox
> tracking. Start with Phase 0 cleanup. Do not implement pointer, keyboard, or
> global macOS control until the command down-channel, signed envelopes,
> authoritative audit tables, local stop, and approval gates are in place.

Date: 2026-06-05
Operator: Simon Aguilera
Status: Implementation in progress
Scope: `apps/luna-client`, API/MCP control plane, desktop-control governance
Branch: `codex/luna-phase1-control-plane`

---

## Context

The installed macOS app at `/Applications/Luna.app` currently opens into the
large `Luna OS` Tauri window (`spatial_hud`) before the working chat/session
surface. Live inspection on 2026-06-05 showed:

1. The first visible window is `Luna OS`, with the login form rendered inside
   the spatial surface.
2. After logging in through `Luna OS`, the smaller `Luna` chat window appears
   but still shows its own login form. Login is not reliably app-wide across
   Tauri windows.
3. The `Luna` window works after logging in directly: sessions list, active
   chat thread, trust badge, memory toggle, screenshot button, and input.
4. The `Luna OS` surface remains open after login. After dismissing the
   overture, it is mostly an empty dark canvas with notification chips,
   `SLEEPING`, `Finale`, and push-to-talk.
5. The gesture/camera engine starts immediately after login and emits high
   volume gesture logs even while the spatial surface says `SLEEPING`.

The product goal is to extend Luna Tauri into a governed macOS computer-use
surface similar in capability class to Codex Computer Use / Claude cowork:
observe the desktop, reason through AgentProvision, and control macOS apps
through pointer, keyboard, clipboard, app/window context, and screenshots.

Luna-facing review was gathered with `alpha chat send`. The strongest guidance:
fix chat-first UX and auth first; make computer-use a visible governed mode
with Observe / Assist / Control / Stop; never auto-start camera or control as
ambient background behavior.

Additional discovery inputs:

1. Live app inspection through macOS confirmed the split-window auth behavior,
   the chat/session surface as the useful primary UI, and the empty `Luna OS`
   spatial surface as the current startup problem.
2. Local architecture review converged on the same constraint: Tauri should be
   the governed actuator, not the agent brain.
3. `alpha run --fanout claude,codex,gemini --merge council` returned only the
   Codex leg because the local alpha backend reported unsupported platforms for
   the other legs. The useful recommendation was to combine a local desktop
   bridge, API-mediated MCP control plane, approvals, authoritative audit, and
   direct Tauri capability cleanup.
4. A separate Claude Opus architecture review recommended signed short-TTL
   action envelopes, first-class shell capability manifests, separate consent
   tiers, and prompt-injection handling for screen/clipboard content.
5. The web Alpha Control surface provides reusable UI patterns for session
   events, activity panels, terminal/action feeds, command palette behavior,
   and multi-pane chat workspaces.
6. Local release verification on 2026-06-05 installed `luna-v0.1.71` from
   GitHub Releases over local `0.1.68`. The app launched, but release smoke
   found four shipping issues: startup still opens `Luna OS` instead of chat,
   updater fetch fails because the manifest endpoint is not Luna-specific,
   the release manifest had an empty updater signature, and the DMG was
   ad-hoc signed rather than Developer ID signed/notarized.
7. Claude Code Superpowers review on 2026-06-05 found plan-level blockers to
   close before Phase 2: define `shell_id` generation/persistence, specify the
   atomic approval-consumption mechanism, make migration-number lookup explicit,
   include Ed25519 key lifecycle, and move Helm/env sync into the phase that
   introduces signing/device secrets.
8. PR #779 merged Phase 0 release/safety hardening on 2026-06-06 UTC. The
   `luna-v0.1.82` GitHub Actions release succeeded as an unsigned development
   prerelease, did not become the repository latest release, published only the
   manual DMG plus checksum, and skipped signed updater artifacts as expected.
   Local install from the release DMG reported app version `0.1.82`; Computer
   Use verified chat-first startup, no Orchestra/Luna OS auto-open, Observe ->
   Lock -> Observe, hard Stop latching, and locked startup after relaunch.
9. Release smoke also found that the `luna-v0.1.82` `.sha256` file recorded
   the CI build path instead of the DMG basename. The digest was correct, but
   `shasum -c` failed after downloading the assets into a normal folder. Future
   release checksums must use the DMG basename so operators can verify them
   directly after download.
10. PR #780 fixed future checksum assets and triggered `luna-v0.1.83`.
    GitHub Actions built and published the unsigned prerelease successfully;
    the downloaded `.sha256` verified directly with `shasum -c`, and the DMG
    installed locally as `/Applications/Luna.app` version `0.1.83`. Computer
    Use again verified chat-first startup, no Orchestra/Luna OS auto-open,
    Observe -> Lock -> Observe, and hard Stop latching. The run still spent
    about nine minutes in `actions/checkout` and emitted `fetch-pack` early EOF
    annotations despite succeeding; release checkout/versioning must stop
    requiring full repository history.
11. PR #781 replaced full-history release checkout with shallow checkout,
    tag/release-based Luna patch allocation, per-ref release concurrency, and
    remote-tag ownership verification before publishing. Main run
    `27050451674` produced `luna-v0.1.84` in 3m51s, down from 14m09s on
    `0.1.83`; checkout used `fetch-depth: 1` and completed in seconds. The
    `0.1.84` DMG checksum verified directly with `shasum -c`, installed into
    `/Applications/Luna.app`, and Computer Use verified chat-first startup,
    Observe -> Lock -> Observe, hard Stop latching, and locked startup after
    relaunch.
12. Local validation on 2026-06-06 found Luna's "not responsive" symptom was
    caused by the local production API/tunnel/worker stack, not the Tauri UI.
    Docker had recreated `api`, `cloudflared`, `orchestration-worker`, and
    `code-worker` from a stale Actions runner checkout without `apps/api/app`
    or `cloudflared/credentials.json`, causing API import failures, worker
    `ModuleNotFoundError: No module named 'app'`, and Cloudflare `530` / tunnel
    origin failures. Recreating those services from this checkout restored
    `https://agentprovision.com/api/v1` to `200`; Computer Use then verified
    `/Applications/Luna.app` could log in again and return to the chat/session
    surface.

---

## Goals

1. Make `main` chat/sessions the primary Luna Tauri surface.
2. Demote `spatial_hud` to an opt-in Labs/Presence surface.
3. Stop camera/gesture startup unless the user explicitly enables a feature
   that requires it.
4. Add a governed local computer-use actuator in Tauri:
   - screenshot
   - active app/window context
   - clipboard read/write
   - pointer move/click
   - keyboard typing / key chords
   - local stop/pause
5. Route decisions through AgentProvision:
   - Luna/chat/agent -> MCP tool -> API authorization/audit -> desktop action
   - Tauri executes only approved, scoped action envelopes
6. Persist an authoritative replayable audit trail in desktop-control tables and
   mirror display-safe rows into `session_events`.
7. Enforce tenant, user, session, shell/device, and capability scoping on every
   command and result.

## Non-Goals

1. Do not ship global pointer/keyboard control in the first PR.
2. Do not delete the spatial HUD code in the cleanup phase; disable and demote
   it first.
3. Do not make the browser/frontend directly decide dangerous desktop actions.
4. Do not store or transmit the login credentials used during inspection.
5. Do not treat screenshots, clipboard content, OCR text, or page content as
   trusted instructions.
6. Do not use the camera/gesture stack as the policy layer for computer use.

---

## Architecture

```
User / Luna chat
      |
      v
AgentProvision API + agent router
      |
      v
MCP desktop_control tools
      |
      v
API desktop command queue / down-channel
      |
      v
Luna Tauri local actuator
      |
      v
macOS Accessibility / Screen Capture / Clipboard / App context
      |
      v
desktop_command_events audit + session_events display mirror
```

### Core Rule

Tauri is the governed actuator, not the brain. It owns local macOS authority,
permission checks, command execution, and the local kill switch. AgentProvision
owns routing, authorization, policy, audit, and user/session context.

Agent-initiated observations and actions must use the same governed route:
MCP tool -> API authorization/audit -> Tauri command or observation request ->
result event. Local user-clicked screenshot or clipboard actions can call local
commands, but they must be labeled `local_user_initiated`, pass local policy,
and still emit audit.

The WebView must not retain broad ambient desktop authority. Before desktop
control ships, replace or remove broad Tauri `shell:default` capability and keep
desktop control behind explicit allow-listed Tauri commands plus the
`desktop_control` tool group.

### Release Channel Rule

Luna desktop releases are built only by GitHub Actions and distributed only
through GitHub Releases. Do not build production Tauri releases locally.

Release hardening requirements:

1. The updater endpoint must be Luna-specific. It cannot use
   `/releases/latest/download/latest.json` because CLI releases can become the
   repository's latest release.
2. The updater endpoint must point at `nomad3/agentprovision-agents`, not the
   pre-rename `servicetsunami-agents` repository.
3. Release `latest.json` must point at a Tauri updater archive
   (`Luna.app.tar.gz`), not the manual DMG, and must include the archive's
   non-empty updater signature when the app embeds a non-empty updater pubkey.
4. The release workflow must fail rather than publish an unsigned updater
   manifest.
5. Before broad macOS control ships, the app must be Developer ID signed,
   notarized, stapled, and verified in CI before publishing the release.
6. Local installation is allowed only as smoke verification of a GitHub Release
   artifact.
7. Published `.sha256` assets must contain the DMG basename, not the CI build
   path, so `shasum -c Luna_<version>_aarch64.dmg.sha256` works after a normal
   release download.
8. The release workflow must use shallow checkout and tag-based Luna patch
   allocation instead of `git rev-list --count` over full history. Main-branch
   release builds must be serialized so two queued builds cannot claim the
   same next Luna version.

### Alpha Control Reuse

Reuse the web frontend's Alpha Control patterns where they fit the desktop
client:

1. Session activity timeline: adapt `SessionEventsContext`,
   `useV2SessionEvents`, and `AgentActivityPanel` behavior for desktop action
   replay.
2. Operator command affordances: borrow command palette and explicit action
   rows, but keep Luna Tauri chat-first instead of an IDE shell.
3. Multi-session navigation: preserve the existing Luna session list and active
   chat behavior as the primary control surface.
4. Terminal/action feed mental model: represent desktop actions as request,
   approval, start, completion, and denial events.
5. Dense operational UI: avoid landing-page or spatial-first composition for
   the working control surface.

### Capability Tiers

Computer-use permissions must be separate grants, not one broad switch.

| Tier | Capabilities | Default |
|---|---|---|
| Observe | screenshot, active app/window, screen metadata | Off |
| Assist | clipboard read/write, app context, suggested target action | Off |
| Control | pointer move/click, keyboard input, app focus/open | Off |
| Global Control | pointer/keyboard outside Luna/frontmost target | Off, opt-in only |

### Down-Channel

Existing session events solve replay and observation, but not agent-to-desktop
command delivery. Add a new authenticated down-channel for action envelopes.
SSE or polling may notify Tauri that a command is claimable, but Tauri must
claim the command from the API before execution so stale notifications cannot
execute work.

Action envelope shape:

```json
{
  "action_id": "uuid",
  "command_id": "uuid",
  "correlation_id": "uuid",
  "tenant_id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "shell_id": "desktop-...",
  "device_id": "optional durable desktop device id",
  "issuer": "agentprovision-api",
  "policy_version": "desktop-control-v1",
  "capability": "pointer.click",
  "target": {
    "bundle_id": "com.apple.Safari",
    "app": "Safari",
    "window_title": "AgentProvision",
    "window_title_hash": "sha256",
    "display_id": 1,
    "scale_factor": 2.0,
    "bounds": [0, 0, 1496, 933],
    "screenshot_hash": "sha256",
    "observed_at": "2026-06-05T00:00:00Z"
  },
  "args": {
    "x": 512,
    "y": 420
  },
  "approval": {
    "approval_id": "uuid",
    "mode": "one_action",
    "risk_tier": "control",
    "approved_by_user_id": "uuid",
    "approved_at": "2026-06-05T00:00:00Z",
    "expires_at": "2026-06-05T00:00:10Z",
    "capabilities": ["pointer.click"],
    "max_actions": 1,
    "target_binding": {
      "bundle_id": "com.apple.Safari",
      "window_title_pattern": "AgentProvision"
    }
  },
  "issued_at": "2026-06-05T00:00:00Z",
  "expires_at": "2026-06-05T00:00:10Z",
  "nonce": "uuid",
  "seq_no": 123,
  "signature": "base64-ed25519-or-hmac"
}
```

Tauri rejects envelopes when any of these fail:

1. Tenant/user/session/shell does not match the logged-in local shell.
2. Capability is not enabled locally.
3. Signature, issuer, policy version, `issued_at`, `expires_at`, nonce, or
   sequence validation fails.
4. Approval is missing for the requested risk tier.
5. Current active app/window no longer matches the target when the action is
   app-bound.
6. Local kill switch is active.
7. The device claim token is revoked, expired, or no longer bound to the shell.
8. The command lease is missing, expired, duplicated, or owned by another shell.

### Command Lifecycle

`desktop_commands` uses an explicit state machine:

```
pending -> claimed -> running -> succeeded
                           |-> failed
                           |-> denied
                           |-> preempted
pending -> expired
claimed -> expired
```

Rules:

1. Server-generated command IDs and nonces are unique.
2. Status transitions use compare-and-swap semantics.
3. A command can have only one active claim lease.
4. A command can actuate at most once.
5. Duplicate completion is idempotent and cannot create a second success.
6. Stop moves queued or claimed work to `preempted` and rejects completion as
   success.
7. Retries create new commands with new nonces and correlation to the original
   request.
8. Approval consumption uses a database compare-and-swap update on the approval
   row inside the same transaction as command claim. The update must include
   `remaining_actions > 0`, `expires_at > now()`, target binding, capability,
   and tenant/user/session predicates. If the update affects zero rows, the
   command claim is denied.

### Device Trust Bootstrap

Desktop shell identity is durable and revocable:

1. `device_registry` grows a `desktop` device type for enrolled Luna Tauri
   shells.
2. Enrollment creates a rotating desktop claim token and a local signing or
   verification keypair.
3. The API stores only hashed claim secrets and public key material.
4. `shell_id` is a random UUID generated on first successful desktop login and
   persisted in Tauri app data storage. It is not derived from hostname, user
   name, or hardware identifiers. Reinstall or explicit device reset can rotate
   it.
5. Presence binds liveness to `device_id`, `shell_id`, app version, hostname
   hash, OS username hash, and current capability manifest.
6. Command claim requires both a logged-in user session and a valid desktop
   device claim token.
7. Operators can revoke or rotate desktop device tokens without disabling user
   login.

### Up-Channel And Audit

`desktop_command_events` is the authoritative append-only audit trail.
`session_events` mirrors display-safe timeline rows for chat/activity replay and
must not be the command queue or sole audit store.

Desktop event payloads include:

```json
{
  "desktop_action_id": "uuid",
  "desktop_command_id": "uuid",
  "approval_id": "uuid|null",
  "correlation_id": "uuid",
  "tenant_id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "shell_id": "desktop-...",
  "device_id": "uuid",
  "capability": "pointer.click",
  "source": "mcp|local_user|api|tauri",
  "created_at": "timestamp"
}
```

Events include:

| Event type | Payload |
|---|---|
| `desktop_observation_captured` | screenshot/app/window/clipboard metadata |
| `desktop_action_requested` | proposed action envelope summary |
| `desktop_action_approved` | approval source and scope |
| `desktop_action_started` | action id, capability, target |
| `desktop_action_completed` | success/failure, latency, active-app check |
| `desktop_action_denied` | denial reason |
| `desktop_control_stopped` | local/API stop source |

---

## UX Direction

Luna Tauri should be calm and useful by default. Computer use should be visibly
armed, scoped, reversible, and audited.

Main chat window control strip:

```
[Observe] [Assist] [Control] [Stop]
```

Required UX states:

1. `Idle`: no screen, clipboard, pointer, keyboard capability active.
2. `Observing`: screenshots/app context allowed for the current session.
3. `Assisting`: clipboard/context helpers active; Luna can propose actions.
4. `Controlling`: pointer/keyboard control armed; prominent indicator visible.
5. `Stopped`: local kill switch active; all queued commands rejected.

First-use permission sheet:

1. What Luna wants to access.
2. Which session/device the grant applies to.
3. Duration: one action, 10 minutes, or until stopped.
4. Audit: always enabled.
5. Exact capabilities toggled independently.
6. Whether raw pixels/text may leave the device, or metadata-only observation is
   required.

Just-in-time approval policy:

| Action | Approval |
|---|---|
| Active app/window metadata | session-level approval |
| Screenshot | session-level approval, with visible indicator |
| Clipboard read/write | confirm on sensitive-looking content |
| Pointer movement/click | show intent first in v1 |
| Keyboard input | explicit approval |
| Form submit/send/delete/purchase/local destructive UI | explicit action-time approval |

### Approval Grant Semantics

Approval grants must be explicit records, not loose UI state:

1. Each grant has `approval_id`, `risk_tier`, capabilities, approver user ID,
   target binding, expiry, and max action count.
2. Approval is consumed or decremented atomically during command claim or
   execution.
3. Broad session approvals never cover keyboard, destructive UI, shell,
   clipboard write, or global-control actions.
4. Expired or target-mismatched approvals fail closed.
5. Approval records are included in `desktop_command_events` for replay.

### Pending Action Review

Every non-observation command appears in a pending-action queue before execution
unless it is covered by a still-valid one-action approval.

Each row shows:

1. Requested capability.
2. Target app/window and bundle ID.
3. Reason supplied by the agent.
4. Exact action arguments summarized safely.
5. Approval scope and expiry countdown.
6. `Approve Once`, `Deny`, and `Stop All` actions.

Unknown, destructive, cross-app, keyboard, and global-control actions default to
deny until explicitly approved. Broad session approvals cannot be reused for
keyboard or destructive UI.

### Stop Semantics

Stop is a hard local safety control, not only UI state:

1. Stop cancels queued, claimed, and in-flight commands.
2. Stop revokes current Observe, Assist, Control, and Global Control grants.
3. Stop disables actuator threads locally before network calls.
4. Subsequent claim and completion calls return or record `stopped`.
5. Stop state survives reconnect and app relaunch until the user clears it.
6. Stop emits `desktop_control_stopped` into authoritative audit and the
   display-safe timeline.

---

## File Map

### Existing files to modify first

```
apps/luna-client/src-tauri/tauri.conf.json
apps/luna-client/src/App.jsx
apps/luna-client/src/components/ChatInterface.jsx
apps/luna-client/src/hooks/useShellPresence.js
apps/luna-client/src/hooks/useSessionEvents.js
apps/luna-client/src-tauri/src/lib.rs
apps/luna-client/src-tauri/src/gesture/cursor.rs
apps/luna-client/src-tauri/capabilities/default.json
apps/luna-client/README.md
CLAUDE.md
.github/workflows/luna-client-build.yaml
apps/api/app/services/tool_groups.py
apps/api/app/api/v1/devices.py
apps/api/app/models/device_registry.py
apps/api/app/api/v2/session_events.py
apps/api/app/services/collaboration_events.py
apps/mcp-server/src/tool_audit.py
apps/mcp-server/src/mcp_tools/__init__.py
```

### New files expected

```
apps/luna-client/src-tauri/src/computer_use/mod.rs
apps/luna-client/src-tauri/src/computer_use/types.rs
apps/luna-client/src-tauri/src/computer_use/permissions.rs
apps/luna-client/src-tauri/src/computer_use/actuator.rs
apps/luna-client/src-tauri/src/computer_use/commands.rs
apps/luna-client/src/components/computer-use/ComputerUseControlStrip.jsx
apps/luna-client/src/components/computer-use/ComputerUsePermissionSheet.jsx
apps/luna-client/src/components/computer-use/DesktopActionReviewQueue.jsx
apps/luna-client/src/hooks/useComputerUseChannel.js

apps/api/app/models/desktop_command.py
apps/api/app/models/desktop_command_event.py
apps/api/app/services/desktop_control_service.py
apps/api/app/api/v1/desktop_control.py
apps/api/migrations/NNN_desktop_control_commands.sql
apps/api/migrations/NNN_device_registry_desktop.sql

apps/mcp-server/src/mcp_tools/computer_use.py
```

Migration number `NNN` must be chosen from the next available migration at
implementation time, then inserted into `_migrations` per repo convention.
Use:

```bash
ls apps/api/migrations/*.sql | sort | tail -1
```

Then force-add SQL files because migration files can be ignored by local/global
gitignore rules:

```bash
git add -f apps/api/migrations/NNN_*.sql
```

---

## Phasing

### Phase 0 -- Chat-first cleanup

Goal: make the working chat/session UI the product surface and stop the broken
orchestra hub from opening by default.

- [x] Set `main` visible on startup in `tauri.conf.json`.
- [x] Set `spatial_hud` hidden on startup, or gate it behind a feature flag.
- [x] Update tray click and "Open" menu to focus `main`, not `spatial_hud`.
- [x] Keep "Open Luna OS / Labs" as an explicit menu item if needed.
- [x] Update `Cmd+Shift+L` semantics to focus/toggle chat, not spatial HUD.
- [ ] Verify `Cmd+Shift+Space` opens the command palette on `main`, not
      `spatial_hud`.
- [x] Update `CLAUDE.md` and `apps/luna-client/README.md` shortcut docs.
- [x] Remove "Luna OS Spatial Workstation" empty-state copy from the main chat.
- [x] Ensure login state is app-wide across Tauri windows.
- [x] Stop auto-starting `gesture_start` on generic login.
- [x] Gate camera/gesture startup behind an explicit setting or feature use.
- [ ] Throttle gesture logs or move per-frame events to debug-only logs.
- [x] Confirm `App.jsx` no longer calls `gesture_start` or camera capture after
      generic login.

Exit criteria:

- [x] App opens directly to `Luna` chat/session window.
- [ ] Login once is enough for all Tauri windows.
- [x] `Luna OS` window does not open unless explicitly requested.
- [x] Camera indicator does not activate on login.
- [x] Gesture logs are quiet in normal runtime.
- [x] Gesture/camera off by default is verified before any observation feature
      work begins.

### Phase 0.5 -- Release channel hardening

Goal: make the GitHub Actions/GitHub Releases path trustworthy before shipping
desktop-control capabilities.

Current verification finding (2026-06-06):

- [x] PR #777 fixed the self-hosted macOS runner checkout blocker by moving
      Luna release checkout into a per-run isolated path. Main run
      `27047038881` completed checkout, dependency install, and version
      calculation.
- [x] Development builds are intentionally unsigned for now. The Luna release
      workflow now falls back to `cargo tauri build --no-sign` when Apple/Tauri
      signing secrets are absent, uploads the DMG plus SHA256, and labels the
      GitHub Release as an unsigned development build.
- [x] Signed updater publication remains signed-only. The workflow generates
      `latest.json`, uploads `Luna.app.tar.gz` plus `.sig`, and updates
      `luna-latest` only when signing secrets are complete.
- [x] Local unsigned-DMG verification is required for this development phase.
      Signed released-DMG/updater verification is deferred until Apple
      notarization and Tauri updater signing are re-enabled.
- [x] Local unsigned app-bundle smoke completed from branch
      `codex/luna-dev-unsigned-safety`: built with
      `cargo tauri build --debug --bundles app --no-sign`, installed into
      `/Applications/Luna.app`, launched with Computer Use, and verified
      `Control Locked -> Observe -> Lock -> Control Locked` plus Stop latch.

- [x] Change Luna updater endpoint to a Luna-specific manifest URL, for example
      a stable `luna-latest` release asset.
- [x] Replace remaining `nomad3/servicetsunami-agents` release URLs with
      `nomad3/agentprovision-agents`.
- [x] Update `.github/workflows/luna-client-build.yaml` to publish or update a
      stable Luna updater manifest that cannot be shadowed by CLI releases.
- [x] Fail the release workflow if `TAURI_SIGNING_PRIVATE_KEY` is missing when
      producing `latest.json`.
- [x] Enable Tauri updater artifacts and publish `Luna.app.tar.gz` plus its
      generated `.sig` instead of using the DMG as the updater payload.
- [ ] Add release smoke checks for `latest.json` non-empty signature, current
      repo URL, downloadable DMG, and DMG SHA256.
- [x] Add Developer ID signing/notarization to the Luna workflow with CI
      verification via `codesign`, `stapler`, and `spctl`.
- [x] Allow unsigned development releases without producing an unsigned updater
      manifest.

Exit criteria:

- [ ] Installed signed Luna can fetch a valid updater manifest once signing is
      re-enabled.
- [ ] Signed `latest.json` points at `nomad3/agentprovision-agents` and
      includes a non-empty signature.
- [x] The release path documents GitHub Actions/GitHub Releases for release
      artifacts and local unsigned builds for development smoke only.
- [x] Local install smoke from the unsigned development app bundle confirms
      version, launch, Observe/Lock, and Stop behavior.

### Phase 1 -- Governed observation, Stop, and privacy baseline

Goal: ship read-only computer-use primitives with audit and explicit UX.

- [ ] Add `computer_use` Rust module and move read-only primitives behind it.
  - [x] Add Phase 1 `computer_use` module for permission readiness; moving
        screenshot/app/clipboard primitives fully behind module boundaries is a
        follow-up.
- [ ] Wrap existing screenshot, active app/window, and clipboard-read commands
      behind one Rust policy gate with mode checks, session binding, audit, and
      local Stop checks.
- [x] Remove or narrow broad Tauri `shell:default` capability before adding
      desktop control.
- [ ] Add local permission state for Observe and Assist tiers.
- [x] Add local Tauri safety state for `control_locked`, `observe`, and
      `stopped`.
- [x] Add `control_get_safety_state`, `control_observe_status`, and
      `control_stop_all` Tauri commands.
- [x] Ensure `control_stop_all` clears gesture engine, global cursor mode, and
      local capture state.
- [x] Enforce local Stop in native observation, capture, gesture start/resume,
      HUD focus, global cursor enablement, and cursor actuator entrypoints.
- [x] Keep native pointer actuation hard-locked in `control_locked` and
      `observe`; no pointer/keyboard action is exposed in this slice.
- [x] Add visible Observe/Stop skeleton in the main chat nav.
- [x] Add visible Observe/Assist/Control/Stop control strip in main chat.
- [ ] Add local Stop state, Stop button, tray Stop item, and keyboard Stop
      shortcut before down-channel work.
- [ ] Add persistent Observe/Assist indicator while either tier is active.
- [x] Add durable random `desktop-<uuid>` shell identity persisted in Tauri app
      data, with browser/test fallback.
- [x] Register conservative shell capabilities through `useShellPresence`
      (`observe`, `stop`, `notify`; no pointer/keyboard/local-action claim).
- [x] Sync shell presence capabilities from native control safety state so
      stopped shells do not advertise observation readiness.
- [x] Add explicit gesture engine start paths in calibration and gesture
      settings after removing login-time camera auto-start.
- [x] Require Observe, not merely non-Stopped, for screenshot, active-app,
      clipboard, spatial capture, and gesture engine start/resume commands.
- [x] Gate background clipboard and activity polling behind Observe mode.
- [x] Ensure logout/unmount locks local observation and releases the gesture
      engine without unlatching Stop.
- [x] Keep the Observe/Stop strip visible in gesture settings and Luna OS/Labs.
- [x] Add a visible Lock action so Observe can be turned off without latching
      emergency Stop.
- [x] Retry gesture engine start when Observe is enabled after an initial
      locked-mode denial in gesture settings or calibration.
- [x] Register macOS permission readiness for Screen Recording, Accessibility,
      Automation/System Events, Input Monitoring, camera, and microphone.
  - [x] Keep readiness probes passive on startup: Screen Recording uses
        preflight, Accessibility uses `AXIsProcessTrusted`, and System
        Events/Automation remains `unknown` until an explicit setup flow so
        Luna does not trigger TCC prompts by merely opening the chat window.
- [x] Add unit coverage for the Phase 1 permission-readiness status contract.
- [ ] Add `desktop_control` tool group in `tool_groups.py`.
- [ ] Add MCP tools:
  - [ ] `desktop_observe_screen`
  - [ ] `desktop_get_active_app`
  - [ ] `desktop_read_clipboard`
- [ ] Ensure agent-initiated observations go through MCP/API governance, not
      direct frontend invokes.
- [ ] Emit authoritative observation events into `desktop_command_events` and
      display-safe summaries into `session_events`.
- [ ] Set screenshot retention default to ephemeral or short-lived object
      storage with TTL.
- [ ] Store clipboard observations as metadata, hashes, and redacted summaries by
      default, not raw text.
- [ ] Add user-visible "delete observations for this session" action.
- [ ] Add unit tests for permission-denied paths.

Exit criteria:

- [ ] Luna can request a screenshot through MCP/API and receive an audited
      result.
- [ ] No pointer/keyboard action exists yet.
- [ ] Tenant/session/shell are present on every observation result.
- [ ] Stop rejects observation requests and records `desktop_control_stopped`.
- [ ] Raw screenshot pixels or clipboard text are never written to
      `session_events`, tool arguments, logs, or long-lived database rows by
      default.

### Phase 2 -- Command down-channel

Goal: add the missing API-to-Tauri path for action envelopes.

- [ ] Add `desktop_commands` table with tenant/user/session/shell scoping.
- [ ] Add append-only `desktop_command_events` table for authoritative audit.
- [ ] Add API service for enqueue, claim, complete, deny, expire.
- [ ] Add desktop device enrollment, claim token hashing, rotation, and
      revocation through `device_registry`.
- [ ] Add Ed25519 key lifecycle: key generation during enrollment, public key
      storage in `device_registry`, private key storage in Tauri secure storage,
      and rotation/revocation.
- [ ] Bind shell presence to `device_id`, `shell_id`, app version, hostname hash,
      OS username hash, and current capability manifest.
- [ ] Add authenticated Tauri polling/SSE hook for claimable-command notices.
- [ ] Require Tauri claim before execution; down-channel notices alone never
      execute commands.
- [ ] Add signed action envelope validation in Tauri.
- [ ] Add server-time TTL, nonce storage, monotonic per-device sequence numbers,
      and replay-window cleanup.
- [ ] Add one active claim lease per command, compare-and-swap status
      transitions, retry limits, and duplicate completion handling.
- [ ] Add atomic approval consumption/decrement during command claim or
      execution.
- [ ] Implement approval consumption as a database compare-and-swap update inside
      the command claim transaction.
- [ ] Add command correlation IDs across API, Tauri, MCP, audit, and
      `session_events`.
- [ ] Add config/env/Helm updates in the same PR as any signing, enrollment, or
      device-token secret.
- [ ] Emit `desktop_action_requested`, `started`, `completed`, `denied`, and
      `stopped`.
- [ ] Add stale-shell rejection.
- [ ] Enforce MCP `desktop_control` tools through scoped agent-token auth; derive
      tenant/user/session/device from auth-bound context, not LLM-supplied
      arguments.
- [ ] Add API tests for tenant isolation and command ownership.

Exit criteria:

- [ ] A no-op test action can be queued by API, claimed by Tauri, and completed
      into `desktop_command_events` and mirrored into `session_events`.
- [ ] Commands for another tenant/user/session/shell are rejected.
- [ ] Expired commands are not executed.
- [ ] Revoked desktop devices cannot claim commands even if shell presence is
      fresh.
- [ ] Stop rejects queued and claimed no-op commands before pointer control
      begins.

### Phase 3 -- Local pointer control

Goal: add the smallest useful actuation path while preserving current safety
defaults.

- [ ] Refactor `gesture/cursor.rs` enigo wrapper into reusable actuator code.
- [ ] Add `pointer_move` and `pointer_click` commands.
- [ ] Keep global cursor mode off by default.
- [ ] Require an observation snapshot with `observed_at`, display ID, scale
      factor, window bounds, active app bundle ID, title hash, and screenshot
      hash.
- [ ] Require target active-app/window validation immediately before click; on
      mismatch, deny and require re-observation.
- [ ] Require visible Control mode before any pointer command.
- [ ] Add persistent Control indicator while pointer control is active.
- [ ] Limit pointer click to safe allow-listed test apps/windows until
      destructive-action classification exists.
- [ ] Require action-time approval for unknown click targets.
- [ ] Add pending-action review queue before pointer click execution.
- [ ] Add Accessibility/Input Monitoring permission readiness checks.
- [ ] Add rate limits for pointer actions.
- [ ] Add UI timeline rows for pointer actions.

Exit criteria:

- [ ] Pointer actions work only when Control is armed.
- [ ] Local Stop blocks action execution without network.
- [ ] Clicks are denied when active app/window drifts from target.
- [ ] Pointer click is limited to allow-listed safe apps/windows until
      destructive-action classification and approval are in place.

### Phase 4 -- Keyboard, clipboard write, app focus

Goal: expand from pointer-only control to real app work.

- [ ] Add keyboard type and key-chord primitives.
- [ ] Add clipboard-write primitive with just-in-time approval.
- [ ] Add app focus/open primitive through allow-listed macOS mechanisms.
- [ ] Add per-capability settings in the permission sheet.
- [ ] Add deny-list for sensitive apps/windows.
- [ ] Add confirmation for form submission, send actions, file deletion, and
      destructive UI.
- [ ] Add redaction/sensitivity classifier for clipboard and screenshot OCR
      summaries before agent use.
- [ ] Add action intent classification for click and keyboard targets.
- [ ] Add deny-by-default handling for clipboard contents that look like
      credentials or secrets.

Exit criteria:

- [ ] Luna can type into an explicitly approved target app/window.
- [ ] Clipboard writes are audited and approved.
- [ ] Sensitive action categories require action-time approval.

### Phase 5 -- Global control and production hardening

Goal: allow powerful cross-app work only after the safety surface is proven.

- [ ] Add optional Global Control tier.
- [ ] Add incident replay view from `desktop_command_events` with display-safe
      `session_events` mirror.
- [ ] Add end-to-end tests for stale command, app drift, kill switch, and
      tenant isolation.
- [ ] Add end-to-end tests for stop-during-pointer-move,
      stop-after-claim-before-execute, stale command after stop, and reconnect
      after stop.
- [ ] Add Helm/Terraform/env sync if new service env vars are introduced.

Exit criteria:

- [ ] Global control is off by default.
- [ ] User can see and stop every active capability immediately.
- [ ] Audit replay reconstructs every desktop action and result.

---

## Security Invariants

1. Every database row includes `tenant_id`.
2. Every query filters by tenant.
3. Every desktop command is scoped by tenant, user, session, and shell/device.
4. Tauri is allowed to deny commands locally for any reason.
5. API-side approval does not override local Stop.
6. Screen and clipboard content are untrusted input.
7. Screen and clipboard content never grant permission to act.
8. Control grants are time-boxed and revocable.
9. No action executes after envelope expiry.
10. No orphan actions: every request has a result event.
11. Observed screen, OCR, page text, clipboard text, filenames, app titles, and
    window titles are data only. They must be wrapped as untrusted observations
    in prompts and may not override system, developer, tool, or policy
    instructions.
12. Desktop observation tools return structured fields with provenance labels,
    not raw instruction-like content merged directly into agent prompts.
13. Rate limits apply per tenant, user, session, shell/device, capability, and
    target app. Exceeding limits emits `desktop_action_denied` with reason
    `rate_limited`.
14. Raw screenshots, clipboard values, and OCR output are never logged by
    default.
15. The WebView cannot invoke privileged desktop actions except through
    explicit allow-listed Tauri commands that enforce local policy.

## Command Authenticity Invariants

1. Every desktop command envelope is signed by AgentProvision.
2. Tauri verifies signature, issuer, policy version, `issued_at`, `expires_at`,
   nonce, and sequence before execution.
3. Nonces and completed command IDs are stored locally until expiry plus replay
   window.
4. Approval grants are target-bound, capability-bound, time-boxed, and consumed
   according to scope.
5. Device claim tokens are revocable and rotated independently from user auth.
6. Command claim uses a lease with compare-and-swap status transitions.
7. Completion after local Stop is rejected or recorded as stopped, not success.

## Risk Register

| Risk | Mitigation |
|---|---|
| Prompt injection from screen/clipboard | Treat observed content as untrusted; separate observe from act; require approval for actuation |
| Cross-tenant desktop command leakage | Tenant/user/session/shell checks at enqueue, claim, complete, and replay |
| Wrong-app click/typing | Validate active app/window immediately before action |
| Silent camera/gesture operation | Explicit opt-in, visible state, no auto-start on login |
| Accessibility overreach | Separate capability tiers, global control off by default, local kill switch |
| Log/privacy noise | Debug-gate gesture logs, redact sensitive payloads, retention policy |
| Command replay | Short TTL, monotonic seq/nonce, completed/expired terminal states |
| Frontend bypass | MCP/API enqueue only; Tauri validates envelope and local permission state |
| Direct Tauri invoke bypass | Put existing screenshot, active-app, clipboard, and shell capabilities behind local policy gates |
| Session event audit loss | Use `desktop_command_events` as authoritative append-only audit and mirror safe rows to `session_events` only |
| Stale down-channel delivery | Notify only; require API claim lease before execution |
| Revoked desktop shell | Device claim tokens are checked on claim and can be revoked independently |
| TCC permission drift | Probe macOS permissions before each tier arms and emit denial events when revoked |
| Destructive pointer click | Start with safe allow-listed targets, classify action intent, and require action-time approval for unknown/destructive targets |

---

## Test Plan

### API / MCP

- [ ] `desktop_commands` migration applies and records in `_migrations`.
- [ ] `desktop_command_events` migration applies and records in `_migrations`.
- [ ] Command enqueue requires authenticated user and valid session.
- [ ] Command claim requires matching tenant and shell/device.
- [ ] Cross-tenant command claim returns 404 or denial without leaking existence.
- [ ] Expired commands cannot be claimed.
- [ ] Revoked desktop device cannot claim commands.
- [ ] Duplicate command completion is idempotent and does not create multiple
      success events.
- [ ] Command state machine rejects invalid transitions and cannot double-actuate
      one command.
- [ ] Stop changes queued or claimed commands to `preempted`, not `succeeded`.
- [ ] Completion writes `desktop_command_events` and a display-safe
      `session_events` row.
- [ ] MCP tools require `tenant_id`, scoped agent-token auth, and declared
      `desktop_control` tool group.
- [ ] MCP desktop tools derive tenant/user/session/device from auth-bound
      context, not from LLM-supplied tool arguments.
- [ ] Rate limits are enforced per tenant/user/session/shell/capability.
- [ ] Raw screenshot and clipboard values are not written to logs or
      `session_events`.

### Tauri / Rust

- [ ] `cargo check` in `apps/luna-client/src-tauri`.
- [ ] Unit tests for local permission decisions.
- [ ] Actuator denies when Observe/Assist/Control tier is disabled.
- [ ] Actuator denies expired and replayed envelopes.
- [ ] Actuator denies unsigned envelopes and unsupported policy versions.
- [ ] Actuator denies when device claim token is revoked or missing.
- [ ] Actuator requires command claim lease before execution.
- [ ] Pointer action denies on active-app drift.
- [ ] Stop switch blocks pending commands.
- [ ] Stop switch cancels queued, claimed, and in-flight commands.
- [ ] Existing direct screenshot, active-app, clipboard, and shell paths cannot
      bypass the policy gate.
- [ ] macOS permission probes disable unavailable tiers and emit denial events.

### React / UX

- [ ] Luna opens to chat/session window.
- [ ] Login is shared across windows.
- [ ] Spatial HUD opens only by explicit action.
- [ ] Camera/gesture engine does not start on login.
- [ ] Control strip shows Idle/Observing/Assisting/Controlling/Stopped states.
- [ ] Permission sheet toggles independent capabilities.
- [ ] Permission sheet shows macOS Screen Recording, Accessibility, Automation,
      and Input Monitoring readiness.
- [ ] Pending action queue shows capability, app/window, reason, safe args,
      expiry, Approve Once, Deny, and Stop All.
- [ ] Action feed renders desktop events.
- [ ] Display-safe timeline rows never show raw clipboard secrets or full
      screenshots by default.

### Manual macOS smoke test

- [ ] Fresh launch: only `Luna` chat visible.
- [ ] Sign in once; no second login prompt appears.
- [ ] Open Labs/Spatial explicitly; close it without losing chat.
- [ ] Enable Observe; capture screenshot; verify event appears in chat activity.
- [ ] Revoke Screen Recording while app is running; Observe disables and emits
      denial.
- [ ] Enable Control; perform one pointer move/click in a safe allow-listed test
      app.
- [ ] Move or switch the target app between observation and click; click is
      denied.
- [ ] Press Stop; verify subsequent queued commands are denied.
- [ ] Press Stop after command claim but before execution; command records
      stopped, not success.

---

## Open Questions

1. Should durable desktop identity live only in presence shell registration, or
   should `device_registry` grow a `desktop` type for tokenized command claim?
   Default recommendation: use both -- presence for liveness, device registry
   for durable identity and token rotation.
2. Should screenshots be stored as files, short-lived blobs, or only passed as
   base64 in a single chat turn? Default recommendation: short-lived object
   storage with retention policy; no permanent storage by default.
3. Should OCR/screen element extraction run locally in Tauri or in the API?
   Default recommendation: start with screenshots + metadata; add local OCR
   only after control governance is stable.
4. Should spatial HUD survive as a product surface? Default recommendation:
   keep as Labs/Presence until it earns a concrete workflow.
5. Which command-envelope signature mechanism should ship first: Ed25519
   per-device keypairs or HMAC with rotated device claim secrets? Default
   recommendation: Ed25519 for command authenticity; keep claim token as a
   separate bearer credential.
6. Should command delivery use SSE, WebSocket, or long-poll? Default
   recommendation: use SSE or polling only as notification, with mandatory API
   claim lease before execution.
7. Which current Tauri shell capabilities are still required after chat-first
   cleanup? Default recommendation: remove broad shell access and re-add only
   explicit allow-listed scopes with tests.

---

## Next Actions

1. Validate and merge the Phase 1 permission-readiness/control-strip slice on
   branch `codex/luna-phase1-control-plane`.
2. Re-run local Luna release smoke after the next GitHub Actions prerelease.
3. Continue Phase 1 by moving screenshot, active-app, and clipboard-read
   primitives fully behind the `computer_use` module and adding audit event
   plumbing.
4. Add the `desktop_control` tool group and read-only MCP/API observation tools
   only after the local policy/audit boundary is in place.
5. Do not implement pointer, keyboard, clipboard-write, or global control until
   Phase 1 audit and Phase 2 command-governance exit criteria are satisfied.
