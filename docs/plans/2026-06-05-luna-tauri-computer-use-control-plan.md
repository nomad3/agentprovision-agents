# Luna Tauri Computer Use Control Plan

> For agentic workers: implement this plan phase-by-phase using checkbox
> tracking. Start with Phase 0 cleanup. Do not implement pointer, keyboard, or
> global macOS control until the command down-channel, signed envelopes,
> authoritative audit tables, local stop, and approval gates are in place.

Date: 2026-06-05
Operator: Simon Aguilera
Status: Phase 1 audit spine + read-only MCP observation tools merged; Phase 2
session ownership and device-bound shell identity merged; `luna-v0.1.94`
installed-release validation complete; command down-channel planning active
Scope: `apps/luna-client`, API/MCP control plane, desktop-control governance
Branch: `codex/luna-phase1-control-plane`; current validation-doc branch:
`codex/luna-v0194-validation-doc`

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
13. PR #783 merged the long-term Docker Desktop deploy fix and Luna startup
    maximization on 2026-06-06 UTC. Main workflows passed for Tests, Docker
    Desktop Deployment, and Luna Client Tauri Build, producing unsigned
    development prerelease `luna-v0.1.86`. App-side release validation
    downloaded the DMG plus checksum, verified `shasum -c`, installed
    `/Applications/Luna.app` version `0.1.86`, and launched the installed app
    directly into the maximized chat/session window. Computer Use verified
    `Control Locked`, disabled Assist/Control buttons, no accidental Control
    enablement, and an Alpha chat response from Luna Supervisor. Host-level
    Docker inspection found no `/actions-runner/_work` bind mounts, but Luna's
    exact release-gate command,
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`,
    still printed the named `agentprovision-agents_workspaces` Docker volume
    before the follow-up local compose volume rename.
14. The exact Luna mount gate is now actionable by renaming the local Docker
    workspace volume source away from `_work`: compose still uses the logical
    `workspaces` key and containers still mount `/var/agentprovision/workspaces`,
    but the physical Docker volume defaults to
    `agentprovision-agents_tenant_spaces`. The deploy workflow runs
    `scripts/migrate_compose_workspaces_volume.sh` before `docker compose up`
    to copy existing tenant workspace data from the old
    `agentprovision-agents_workspaces` volume once, quiescing `api` and
    `code-worker` only when a copy is required. Council review added explicit
    in-progress and completion markers so a partial copy cannot be mistaken for
    a finished migration, and the workflow now runs migration plus `up` in one
    recovery-trapped step. The recovery path checks the completion marker: if
    migration has not completed it restarts existing containers, but after a
    completed migration it only recreates `api` and `code-worker` against the
    new volume so old-volume writes cannot be stranded. Local validation after
    the migration returned no output for Luna's exact `_work` smoke command;
    live mounts now source `/var/agentprovision/workspaces` from
    `agentprovision-agents_tenant_spaces`; local API, web, Luna web, and public
    tunnel endpoints returned `200`.
15. Follow-up release validation on 2026-06-06 installed GitHub prerelease
    `luna-v0.1.87` from the unsigned DMG after direct `.sha256` verification.
    `/Applications/Luna.app` reported version `0.1.87`, launched chat-first in
    the maximized main window, and Computer Use verified the governed strip in
    `Control Locked` with Assist/Control disabled. The native permission strip
    correctly reported denied/not-yet-granted Screen Recording and
    Accessibility (`TCC 1/3`). Pressing Stop latched the app into `Stopped`, and
    relaunch preserved the stopped posture with `Resume` visible.
16. PR #788 merged the local observation policy/audit gate and PRs #790/#791
    then landed global emergency Stop plus expanded TCC readiness details.
    GitHub Actions published unsigned development prerelease `luna-v0.1.90`
    on 2026-06-06 UTC. Local release validation downloaded the DMG and checksum,
    verified `shasum -c`, installed `/Applications/Luna.app` version `0.1.90`,
    and used Computer Use to confirm chat-first maximized startup, `Stopped`
    relaunch persistence, TCC readiness details, `Resume -> Observe`, denied
    screenshot metadata-only audit, and `Stop` relatch. The exact Docker mount
    gate,
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`,
    returned no output.
17. Luna Supervisor reviewed the next branch scope on 2026-06-06 and confirmed
    no product blocker for `codex/luna-desktop-command-events` as long as the PR
    stays limited to authoritative `desktop_command_events` schema/API, active
    session + shell binding, metadata-only local audit forwarding, display-safe
    `session_events` mirror, and tests. She explicitly kept pointer/keyboard,
    Assist, and Control actuation out of scope until signed envelopes,
    approvals, replay protection, and policy enforcement are reviewed.
18. PR #793 added the first API-backed local observation audit spine. The branch
    creates `desktop_commands` and `desktop_command_events`, adds authenticated
    local-observation ingestion, mirrors only display-safe summaries into
    `session_events`, registers the `desktop_control` tool group, and forwards
    Luna Tauri metadata-only audit events with active `chat_session_id` plus a
    durable `desktop-<uuid>` shell id. The first GitHub Actions API unit gate
    exposed stale unit expectations and SQLite-only test fragility rather than
    a desktop-control schema defect: the test suite still expected the old
    Claude setup-token flow, English canned greetings, non-fatal P0a token mint
    failures, and raw PostgreSQL-only SQLAlchemy types under SQLite metadata
    creation. The follow-up patch aligned those tests with current behavior,
    added test-only SQLite compilers for PostgreSQL `UUID`, `JSONB`, `ARRAY`,
    `INET`, and optional pgvector types, restored tenant-wide affect fallback
    for agent emotion reads, made session affect reads ignore SQLite JSON-null
    rows in Python, tightened the reflection safety block for "rate limiting",
    and isolated reset-password limiter state in the security tests. Focused
    validation passed locally with 105 API tests plus targeted `ruff`; full PR
    CI remains the merge gate.
19. Cross-CLI review on PR #793 completed with Codex findings; the Claude leaf
    failed on the Alpha backend with `Unsupported platform: claude`, and Luna's
    Alpha chat handoff hit a Cloudflare 524 timeout. Codex found two merge
    blockers: client-controlled `event_id` could smuggle arbitrary display text
    into the mirrored payload, and the Tauri bridge trusted native
    `payload.shell_id` over the active app shell id while the API accepted
    non-connected shell ids. The follow-up patch makes `event_id` a canonical
    UUID at the API boundary, serializes only that UUID into
    `local_event_id`, makes the bridge always use the active `shellId`, and
    rejects audit rows for shells that are not currently connected in Luna
    presence. Durable device-token/session binding remains a Phase 2
    `device_registry` requirement.
20. GitHub API unit CI on PR #793 exposed a long-standing Temporal test hang in
    `SkillEvalIterationWorkflow`: the scaffold intends a failed leg to be
    counted and skipped, but `workflow.execute_activity` used Temporal's default
    retry policy, so the intentionally failing mocked activity retried instead
    of reaching the workflow `except` block. The fix sets
    `maximum_attempts=1` for the scaffold persist and aggregate activities.
    Local validation of `tests/test_skill_eval_iteration_workflow.py` now exits
    cleanly with 3 passing tests.
21. PR #793 validation on head `945ccabf` passed GitHub Actions run
    `27055003884`: API unit in 2m38s, API integration with PostgreSQL/pgvector
    in 4m18s, Luna client jest+cargo in 1m10s, and aggregate status in 7s.
22. PR #793 final head `a5d2891f` passed the required PR gates and merged into
    `main` on 2026-06-06 UTC as merge commit `8c6449cf`. Post-merge GitHub
    Actions passed the broad Tests run `27055213272`, Docker Desktop Deployment
    run `27055213275`, and Luna Client Tauri Build run `27055213274`. The Luna
    build produced unsigned development prerelease `luna-v0.1.92`; signing,
    notarization, and stable updater manifest publication were skipped as
    expected for the current unsigned development release posture.
23. Installed-release validation for `luna-v0.1.92` downloaded
    `Luna_0.1.92_aarch64.dmg` plus `.sha256`, verified directly with
    `shasum -c`, installed `/Applications/Luna.app`, and confirmed bundle
    version `0.1.92` with id `com.agentprovision.luna`. The exact Luna mount
    gate,
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`,
    returned no output. Computer Use verified chat-first maximized startup,
    durable `Stopped` relaunch, `Resume -> Control Locked`, `Observe` without
    unlocking Assist/Control, and `Stop` relatch. TCC readiness remained
    passive: Screen Recording and Accessibility were denied/not-yet-granted,
    System Events was unknown, and no macOS privacy-setting changes were made.
24. Branch `codex/luna-release-validation-phase2` started the next Phase 1
    slice after release validation: MCP desktop observation tools are now
    registered and call an internal-key API request endpoint. The endpoint
    requires auth-bound `X-Tenant-Id` and `X-User-Id`, validates session scope,
    selects only a connected `desktop-<uuid>` shell from Luna presence, derives
    capability from the requested tool/action, and writes display-safe
    `desktop_observation_denied` events while no API-to-Tauri command
    down-channel exists. This intentionally returns no screenshot pixels,
    clipboard text, active-window title, OCR text, bundle id, path, or raw
    desktop content.
25. PR #794 merged the read-only MCP observation request/audit path into
    `main` on 2026-06-06 UTC as merge commit `84d3011b`. Post-merge Tests run
    `27055885443` and Docker Desktop Deployment run `27055885437` passed, and
    Luna's exact Docker mount gate returned no output.
26. PR #795 merged the `chat_sessions.owner_user_id` ownership foundation into
    `main` on 2026-06-06 UTC as merge commit `3065defb`. PR and post-merge CI
    applied migration `159`, API unit/integration coverage passed, broad main
    tests passed, Docker Desktop Deployment run `27056251358` passed, and
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`
    returned no output. Desktop-control now rejects ownerless and same-tenant
    cross-user sessions before selecting a desktop shell.
27. Branch `codex/luna-phase2-device-binding` started the next Phase 2
    prerequisite: Luna desktop enrolls as a `desktop` device through
    `device_registry`, shell presence records an authenticated
    `shell_id -> device_registry.id` binding, and desktop-control audit/MCP
    observation paths fail closed when the connected shell is not device-bound.
28. PR #796 merged the device-bound shell identity prerequisite into `main` on
    2026-06-06 UTC as merge commit `3d9cc323`. Main broad Tests run
    `27056826661`, Docker Desktop Deployment run `27056826668`, and Luna
    Client Tauri Build run `27056826667` all passed. Docker deploy validation
    returned no output for Luna's exact mount gate:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
    Public API validation used the canonical base
    `https://agentprovision.com/api/v1/`, which returned `200`; the
    `api.agentprovision.com` hostname is not the active production API base.
29. Installed-release validation for unsigned development prerelease
    `luna-v0.1.93` downloaded `Luna_0.1.93_aarch64.dmg` plus `.sha256`,
    verified directly with `shasum -c`, installed `/Applications/Luna.app`,
    and confirmed bundle version `0.1.93`. Computer Use verified the
    chat/session surface and the locked desktop safety strip, while direct
    System Events/AppKit measurement exposed that the `maximized` config alone
    is too soft on macOS: the release could launch at a centered offset instead
    of pinning to the visible workspace origin. Follow-up branch
    `codex/luna-default-maximized` adds an explicit native
    `show -> unminimize -> maximize -> focus` path for startup, tray open,
    global shortcut open, and emergency Stop surfacing. Local Tauri dev
    validation measured the branch window at `0,34` with size `1496x933`,
    exactly matching AppKit's main-screen visible frame.
30. PR #797 merged the explicit native maximize path into `main` on
    2026-06-06 UTC as merge commit `80b642d7`. Post-merge broad Tests run
    `27057233801`, Docker Desktop Deployment run `27057233796`, and Luna
    Client Tauri Build run `27057233812` all passed. The release workflow
    intentionally skipped signing/notarization and stable updater publication
    because development builds remain unsigned for now.
31. Installed-release validation for unsigned development prerelease
    `luna-v0.1.94` downloaded `Luna_0.1.94_aarch64.dmg` plus `.sha256`,
    verified directly with `shasum -c`, installed `/Applications/Luna.app`,
    and confirmed bundle version `0.1.94` with id `com.agentprovision.luna`.
    Codesign verification reported an ad-hoc signature. System Events/AppKit
    measured the installed app window at `0,34` with size `1496x933`, matching
    the primary screen visible frame. Computer Use verified chat/session
    rendering, session creation, the locked `Stopped` safety strip, disabled
    Observe/Assist/Control controls, visible `Resume`, TCC readiness details,
    and a live Alpha Chat response from Luna after the lead handoff. Public API
    validation returned `200`, the live Docker stack stayed healthy, and Luna's
    exact mount gate returned no output:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
32. Post-merge sidecar review found one follow-up gap: the command-palette
    shortcut path still only forces the native
    `show -> unminimize -> maximize -> focus` helper when the main window is
    not visible. If the window is visible but minimized, user-resized, or
    off-position, `Cmd+Shift+Space` may only emit the palette event. Keep the
    Phase 0 command-palette verification item open until that path either
    restores/maximizes/focuses consistently or is explicitly scoped out of the
    next command down-channel branch.

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
  - [ ] Follow-up after PR #797: when `main` is already visible but minimized,
        user-resized, or off-position, the command-palette shortcut should
        restore/maximize/focus consistently before opening the palette.
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
- [x] Verify `luna-v0.1.86` unsigned development release locally: DMG checksum,
      `/Applications/Luna.app` version `0.1.86`, maximized startup,
      Control Locked safety strip, disabled Assist/Control, and Alpha chat
      response. App-side validation passed, and the exact mount smoke command
      returned empty after the workspace volume source was renamed.
- [x] Verify `luna-v0.1.87` unsigned development release locally: DMG checksum,
      `/Applications/Luna.app` version `0.1.87`, maximized chat-first startup,
      Control Locked safety strip, disabled Assist/Control, native TCC readiness
      display, and durable Stop posture after relaunch.
- [x] Verify `luna-v0.1.90` unsigned development release locally after PRs
      #788/#790/#791: DMG checksum, `/Applications/Luna.app` version `0.1.90`,
      maximized chat-first startup, durable `Stopped` relaunch, expanded TCC
      details, `Resume -> Observe`, metadata-only denied screenshot audit, and
      Stop relatch.
- [x] Verify `luna-v0.1.92` unsigned development release locally after PR
      #793: DMG checksum, `/Applications/Luna.app` version `0.1.92`, maximized
      chat-first startup, durable `Stopped` relaunch, `Resume -> Control
      Locked`, `Observe` with Assist/Control still disabled, and Stop relatch.
      The exact Docker `_work` mount smoke command returned no output.
- [x] Verify Docker Desktop deployment no longer bind-mounts the GitHub Actions
      `_work` checkout for source-mounted runtime services. Precise inspection
      found zero `/actions-runner/_work` paths, and Luna's broader `grep _work`
      smoke returns empty after live stack migration.

Exit criteria:

- [ ] Installed signed Luna can fetch a valid updater manifest once signing is
      re-enabled.
- [ ] Signed `latest.json` points at `nomad3/agentprovision-agents` and
      includes a non-empty signature.
- [x] The release path documents GitHub Actions/GitHub Releases for release
      artifacts and local unsigned builds for development smoke only.
- [x] Local install smoke from the unsigned development app bundle confirms
      version, launch, Observe/Lock, and Stop behavior.
- [x] Local install smoke from GitHub Release `luna-v0.1.86` confirms version,
      checksum, maximized launch, locked passive control strip, and live Alpha
      chat response. The mount smoke gate returned empty after the Docker
      workspace volume source migration.
- [x] Local install smoke from GitHub Release `luna-v0.1.87` confirms version,
      checksum, maximized launch, locked passive control strip, TCC readiness
      reporting, and durable Stop after relaunch.
- [x] Local install smoke from GitHub Release `luna-v0.1.90` confirms version,
      checksum, maximized launch, TCC readiness detail, `Resume -> Observe`,
      denied screenshot metadata-only audit, Stop relatch, and durable stopped
      relaunch.
- [x] Local install smoke from GitHub Release `luna-v0.1.92` confirms version,
      checksum, maximized chat-first launch, durable stopped relaunch,
      `Resume -> Control Locked -> Observe`, Assist/Control disabled, Stop
      relatch, and an empty exact Docker `_work` mount gate.

### Phase 1 -- Governed observation, Stop, and privacy baseline

Goal: ship read-only computer-use primitives with audit and explicit UX.

- [ ] Add `computer_use` Rust module and move read-only primitives behind it.
  - [x] Add Phase 1 `computer_use` module for permission readiness; moving
        screenshot/app/clipboard primitives fully behind module boundaries is a
        follow-up.
- [ ] Wrap existing screenshot, active app/window, and clipboard-read commands
      behind one Rust policy gate with mode checks, session binding, audit, and
      local Stop checks.
  - [x] Add one shared Rust observation policy gate for screenshot, active
        app/window, and clipboard read.
  - [x] Enforce `Stopped` and non-Observe denial before native observation work
        begins.
  - [x] Enforce passive local permission readiness before Screen Recording,
        Accessibility, and System Events-backed observations.
  - [x] Emit local metadata-only `desktop-control-audit` events for observation
        start, success, failure, and denial.
  - [x] Gate background clipboard/activity emitters with the same local
        observation policy before emitting frontend events, and emit matching
        local audit events for emitted observations.
  - [x] Keep active app/window observation fail-closed on macOS until an
        explicit System Events setup/probe flow can mark Automation readiness as
        granted.
  - [ ] Bind local observation requests to the active chat session before
        MCP/API-governed observations ship.
    - [x] Add branch `codex/luna-desktop-command-events` bridge that forwards
          existing local `desktop-control-audit` events with active
          `chat_session_id` and durable `desktop-<uuid>` shell id.
  - [x] Promote local audit events into authoritative API
        `desktop_command_events` and display-safe `session_events`.
    - [x] Add authenticated `/api/v1/desktop-control/events/local-observation`
          endpoint that persists metadata-only local observation events into
          `desktop_command_events` and mirrors display-safe payloads into
          `session_events`.
    - [x] Redact unrecognized client-supplied audit `reason` text before
          persistence/mirroring so the reason field cannot smuggle raw
          clipboard, screenshot, window-title, path, or prompt content.
    - [x] Add focused API tests for authenticated ingestion, tenant/session
          binding, allowed metadata keys, display-safe mirroring, and reason
          redaction.
    - [x] Constrain local observation `event_id` to UUID syntax before it can be
          stored as `local_event_id` or mirrored into `session_events`.
    - [x] Reject local observation audit rows for shell ids that are not
          currently connected in Luna presence.
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
- [x] Add local Stop state, Stop button, tray Stop item, and keyboard Stop
      shortcut before down-channel work.
- [ ] Add persistent Observe/Assist indicator while either tier is active.
- [x] Add durable random `desktop-<uuid>` shell identity persisted in Tauri app
      data, with browser/test fallback.
- [x] Register conservative shell capabilities through `useShellPresence`
      (`observe`, `stop`, `notify`; no pointer/keyboard/local-action claim).
- [x] Sync shell presence capabilities from native control safety state so
      stopped shells do not advertise observation readiness.
- [x] Ensure the local audit bridge uses the active app shell id instead of
      trusting a native event payload shell override.
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
- [x] Add `desktop_control` tool group in `tool_groups.py`.
  - [x] Add `desktop_control` group key for the planned read-only observation
        MCP tools; no agent grants or actuation tools are added in this slice.
  - [x] Add CI recovery coverage so existing unit jobs can compile
        PostgreSQL-typed models under SQLite without weakening the real
        PostgreSQL integration gate.
- [x] Add MCP tools:
  - [x] `desktop_observe_screen`
  - [x] `desktop_get_active_app`
  - [x] `desktop_read_clipboard`
  - [x] Current Phase 1 behavior records a governed request/denial through the
        API and returns the audit envelope. Live content delivery remains
        blocked until the Tauri command down-channel ships.
- [ ] Ensure agent-initiated observations go through MCP/API governance, not
      direct frontend invokes.
  - [x] The registered MCP tools call
        `/api/v1/desktop-control/internal/observations/request` with internal-key,
        tenant, and user headers; they do not call native Tauri commands or
        return raw desktop content.
- [ ] Emit authoritative observation events into `desktop_command_events` and
      display-safe summaries into `session_events`.
  - [x] Add Phase 1 local-observation ingestion for `started`, `succeeded`,
        `failed`, and `denied` metadata-only events.
  - [x] Reject unknown/raw payload keys at the API schema boundary and redact
        unrecognized reason text before writing audit rows.
- [ ] Set screenshot retention default to ephemeral or short-lived object
      storage with TTL.
- [ ] Store clipboard observations as metadata, hashes, and redacted summaries by
      default, not raw text.
- [ ] Add user-visible "delete observations for this session" action.
- [ ] Add unit tests for permission-denied paths.
  - [x] Cover local observation-policy denials for stopped, locked,
        Screen Recording denied, Accessibility denied, and System Events
        unknown states.
  - [ ] Cover Tauri command-level denied/error audit emission once the active
        session/API boundary is introduced.

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

- [x] Add `desktop_commands` table with tenant/user/session/shell scoping.
- [x] Add append-only `desktop_command_events` table for authoritative audit.
- [x] Add `chat_sessions.owner_user_id` so desktop-control can reject ownerless
      and cross-user session requests before live content is enabled.
- [ ] Add API service for enqueue, claim, complete, deny, expire.
  - [x] Add API service for local metadata-only observation-event ingestion.
        Enqueue/claim/complete/deny/expire remains pending for signed command
        envelopes.
- [ ] Add desktop device enrollment, claim token hashing, rotation, and
      revocation through `device_registry`.
  - [x] Add authenticated Luna desktop enrollment endpoint that creates or
        updates a `desktop` `device_registry` row for the durable
        `desktop-<uuid>` shell id, stores only the hashed claim token, rotates
        the token on enrollment, and returns the raw token once to the client.
        Operator revocation and claim-time token validation remain pending.
- [ ] Add Ed25519 key lifecycle: key generation during enrollment, public key
      storage in `device_registry`, private key storage in Tauri secure storage,
      and rotation/revocation.
- [ ] Bind shell presence to `device_id`, `shell_id`, app version, hostname hash,
      OS username hash, and current capability manifest.
  - [x] Bind Luna shell presence to authenticated `device_id`, `shell_id`, and
        current capability manifest, then persist the internal
        `device_registry.id` in presence for desktop-control authorization.
        App version/host hash/OS-user hash are still pending.
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
  - [x] Bind desktop observation requests to an authenticated user header and
        reject sessions not owned by that user.
  - [x] Bind shell/device identity to authenticated Luna desktop enrollment
        before even recording MCP observation requests. Screenshots,
        active-app data, clipboard text, and pointer/keyboard command results
        remain blocked until device-token-authenticated command claim and
        signed action envelopes ship.
- [ ] Add API tests for tenant isolation and command ownership.
  - [x] Add focused observation-path tests for ownerless sessions, same-tenant
        cross-user sessions, and user validation before shell selection.
  - [x] Add focused desktop-device enrollment and shell-device binding tests,
        including unbound shell rejection for local and MCP observation paths.

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
- [ ] `chat_sessions.owner_user_id` migration applies, backfills single-user
      tenants only, and records in `_migrations`.
- [x] PR #793 includes migration files for `desktop_commands` and
      `desktop_command_events`; applied-migration validation remains part of
      the PostgreSQL CI/release gate.
- [x] PR #795 migration `159_chat_sessions_owner_user_id.sql` applies in PR and
      post-merge PostgreSQL CI, backfills single-user tenants only, and records
      in `_migrations`.
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
  - [x] PR #794 and the Phase 2 ownership follow-up keep MCP observation tools
        denial-only and require authenticated user/session ownership.
  - [x] Device-bound shell identity is now enforced before local/MCP desktop
        observation audit rows are accepted; live content return remains
        blocked until command claim, signatures, approvals, and Tauri execution
        ship.
- [ ] Rate limits are enforced per tenant/user/session/shell/capability.
- [ ] Raw screenshot and clipboard values are not written to logs or
      `session_events`.
- [x] Focused API validation for PR #793 passed locally:
      `tests/api/v1/test_desktop_control_events.py`,
      `tests/api/v1/test_claude_auth_setup_token.py`,
      `tests/test_cli_dispatch_rollback_safety.py`,
      `tests/test_emotion_engine_agent_affect_endpoint.py`,
      `tests/test_emotion_engine_prompt_injection.py`,
      `tests/test_greeting_template.py`,
      `tests/test_reflection_validators.py`, and
      `tests/test_security_fixes.py` all passed in one run.
- [x] Targeted `ruff check` passed for the desktop-control API/model files and
      touched API test/support files.
- [x] Council-blocker regression checks passed locally after the review fix:
      desktop-control API event tests, Luna audit bridge tests, and targeted
      `ruff`.
- [x] `SkillEvalIterationWorkflow` unit tests pass after disabling activity
      retries for the scaffold failure-counting path.
- [x] Fresh GitHub Actions API unit, API integration, and Luna client gates pass
      on PR #793 after the CI recovery patch.
- [x] Final PR #793 gate passed on head `a5d2891f`; post-merge broad Tests run
      `27055213272` passed on merge commit `8c6449cf`.
- [x] Phase 1 MCP request/audit slice local API validation passed:
      `pytest tests/api/v1/test_desktop_control_events.py -q` (`14 passed`).
- [x] Phase 2 session ownership local API validation passed:
      `pytest tests/api/v1/test_desktop_control_events.py
      tests/test_chat_session_default_agent_and_title.py
      tests/test_api.py::test_create_user_and_tenant
      tests/test_api.py::test_login_for_access_token -q` (`28 passed`).
- [x] Phase 2 device-binding focused local validation passed:
      `pytest tests/api/v1/test_desktop_control_events.py
      tests/api/v1/test_desktop_device_binding.py -q` (`28 passed`) and
      `npm test -- --run src/hooks/__tests__/useShellPresence.test.jsx
      src/utils/__tests__/desktopDeviceEnrollment.test.js` (`3 passed`).

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
- [x] GitHub Luna client `jest + cargo` gate passed on PR #793 and again in
      post-merge main Tests run `27055213272`.
- [x] Phase 1 MCP tool validation passed:
      `pytest tests/test_desktop_control_tool.py -q` in `apps/mcp-server`
      (`6 passed`), plus targeted `ruff` for touched API and MCP files.

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

- [x] Fresh launch: only `Luna` chat visible.
- [x] Fresh launch: installed `luna-v0.1.86` opens maximized by default.
- [x] Fresh launch: installed `luna-v0.1.92` opens maximized by default.
- [x] Fresh launch: installed `luna-v0.1.94` opens expanded by default; System
      Events/AppKit measured `0,34` and `1496x933`, matching the primary
      screen visible frame.
- [x] Fresh launch: Control strip starts `Control Locked`, with Assist and
      Control disabled.
- [x] Fresh launch: installed `luna-v0.1.94` renders chat/session navigation,
      the stopped/locked desktop safety strip, `Resume`, and TCC readiness
      details under Computer Use.
- [x] Fresh relaunch: installed `luna-v0.1.92` starts in durable `Stopped` with
      `Resume` visible.
- [x] `luna-v0.1.92` Computer Use smoke: `Resume -> Control Locked -> Observe`
      keeps Assist/Control disabled, and `Stop` relatches the safe state.
- [x] `luna-v0.1.94` Computer Use smoke: new chat/session creation works and
      Luna responded in Alpha Chat after the computer-use lead handoff.
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

1. Open the next implementation branch for the Phase 2 API-to-Tauri command
   down-channel. First gate: lease/CAS command claim, stale lease expiry,
   duplicate-completion idempotency, and Stop preemption for queued, claimed,
   and in-flight commands.
2. Keep real pointer, keyboard, clipboard-write, and global macOS actuation
   disabled until signed envelopes, replay defense, approval grant consumption,
   device trust checks, and privacy/TCC boundaries are implemented and reviewed.
3. Include the PR #797 command-palette maximize follow-up in the next branch or
   explicitly keep it as a separate UX hardening item.
4. Ask Luna, Claude Code, and Codex council to review the next pushed diff for
   privacy, tenant/session/shell binding, command-state correctness, and
   release-readiness before merge.
5. Keep validating every merged Luna release by installing the GitHub Actions
   DMG locally, smoking it with Computer Use, and rerunning the exact Docker
   `_work` mount gate. The pass condition is zero output.
