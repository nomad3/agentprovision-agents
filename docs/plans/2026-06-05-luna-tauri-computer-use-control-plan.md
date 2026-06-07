# Luna Tauri Computer Use Control Plan

> For agentic workers: implement this plan phase-by-phase using checkbox
> tracking. Start with Phase 0 cleanup. Do not implement pointer, keyboard, or
> global macOS control until the command down-channel, signed envelopes,
> authoritative audit tables, local stop, and approval gates are in place.

Date: 2026-06-05
Operator: Simon Aguilera
Status: Phase 1 audit spine + read-only MCP observation tools merged; Phase 2
session ownership and device-bound shell identity merged; observation-only
command down-channel merged in PR #799; PR #800 client completion hardening
merged and unsigned `luna-v0.1.96` installed locally; PR #801 backend lease
timezone fix merged and deployed; PR #803 native pointer/keyboard scaffold
merged and unsigned `luna-v0.1.97` installed locally; PR #806 native-control
policy hardening merged and unsigned `luna-v0.1.98` installed locally; PR #807
signed desktop command envelope gate merged and unsigned `luna-v0.1.99`
installed locally; PR #808 Alpha CLI async chat-kernel transport merged and
unsigned `luna-v0.1.100` installed locally; PR #810 macOS Alpha-kernel/readiness
merged and unsigned `luna-v0.1.101` installed locally; PR #811 local claimed
command-envelope preflight merged and unsigned `luna-v0.1.102` installed
locally; PR #812 macOS app-monitor event-contract hardening merged and unsigned
`luna-v0.1.103` installed locally; PR #813 explicit approval-grant
creation/claim-time CAS consumption merged and unsigned `luna-v0.1.104`
installed locally. Native actuation remains disabled; the next gated phase is
Alpha-kernel/native-boundary proof before any pointer or keyboard invoke can
ship. Current branch adds first-use macOS permission onboarding actions in the
TCC panel so Luna can guide users to the exact Screen Recording,
Accessibility, Automation, Camera, and Microphone setup flows needed for
end-to-end computer-use validation. Developer ID signing is now being
re-enabled for the release lane with a newly generated Luna signing certificate
and Tauri updater key.
Scope: `apps/luna-client`, API/MCP control plane, desktop-control governance
Current implementation branch: `codex/luna-native-boundary-proof`

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
Architecture constraint: Luna Tauri uses `alpha` CLI as its local kernel for
AgentProvision chat/task execution, session continuity, and CLI-runtime
delegation. Tauri remains the native macOS shell, UI, and governed actuator; it
must not grow a separate ad hoc agent loop that bypasses Alpha CLI.
API/CLI parity constraint: every API capability added for Luna must ship with
matching Alpha CLI/core types or commands in the same implementation slice so
the Tauri app can consume the platform through `alpha` rather than a bespoke
HTTP client path.

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
33. Branch `codex/luna-command-downchannel-gate` implements the first
    API-to-Tauri command down-channel gate without pointer/keyboard actuation:
    internal command enqueue, device-token-authenticated claim leases,
    completion, Stop preemption, stale-lease expiry, duplicate-completion
    idempotency, and a Luna client polling hook mounted only on the
    authenticated chat/session surface. The hook claims observation commands,
    re-checks local `control_get_safety_state`, executes only existing
    read-only native observation commands in Observe mode, and completes with
    metadata-only result summaries. It never forwards screenshot pixels,
    clipboard text, OCR text, active-window text, tokens, or raw desktop
    content through completion metadata. Sidecar review found four safety gaps
    in the initial implementation; the branch now sanitizes completion and Stop
    reasons, allow-lists completion metadata keys, returns terminal duplicate
    completions idempotently even after shell presence drift, emits
    `desktop_command_expired` audit/session events during stale lease sweeps,
    and migrates command nonces from a global unique index to tenant-scoped
    idempotency. Luna lead review in the installed app cleared the branch for
    PR update while keeping real actuation locked. Claude Opus code review
    found no high/medium issues; the two low items were closed by aligning the
    SQLAlchemy nonce index with migration `160` and adding a pending-command
    TTL so stale queued observe commands expire before a later reconnect can
    claim them.
34. PR #799 merged the observation-only command down-channel into `main` on
    2026-06-06 UTC as merge commit `d6405f86`. PR checks passed for API unit,
    API integration, Luna client, and aggregate status; post-merge broad
    Tests, Docker Desktop Deployment, and Luna Client Tauri Build all passed.
    The release workflow published unsigned development prerelease
    `luna-v0.1.95`, intentionally ad-hoc signed with no Developer ID
    notarization. Local install verified `Luna_0.1.95_aarch64.dmg` with its
    `.sha256`, replaced `/Applications/Luna.app`, and confirmed bundle version
    `0.1.95` with id `com.agentprovision.luna`.
35. Installed-release smoke for `luna-v0.1.95` passed the non-command gates:
    Luna launched chat-first, opened expanded across the visible desktop,
    reported the expected unsigned development signature, served the public and
    local API bases, kept the Docker stack healthy, and returned no output for
    Luna's exact mount gate:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
    Computer Use verified `Stopped -> Resume -> Control Locked -> Stop`
    behavior with Observe/Assist/Control still governed by TCC and local mode.
36. Installed command down-channel smoke for `luna-v0.1.95` exposed a client
    hardening gap: an internal `get_active_app` observation command was queued
    and claimed by the installed app, but the Luna client never posted terminal
    completion, so the backend lease expired it. The API correctly recorded
    queued, claimed, and expired audit events, did not persist raw payload text,
    and failed closed, but the installed smoke is not release-complete until a
    claimed command always completes or explicitly fails from the client before
    lease expiry. Follow-up branch `codex/luna-command-completion-smoke-fix`
    adds client-side timeouts around safety checks, native observation invokes,
    and completion POSTs so a stalled Tauri call records `failed` instead of
    waiting for backend expiry.
37. PR #800 merged the client-side claimed-command terminalization hardening
    into `main` on 2026-06-06 UTC as merge commit `49726b06`. Luna lead review
    via Alpha Chat returned merge-ready with one non-blocking caveat:
    cancellation during an already-running safety/native invoke still resolves
    through timeout/success/failure instead of immediate `preempted`. PR checks
    and post-merge broad Tests, Docker Desktop Deployment, and Luna Client
    Tauri Build passed. GitHub Actions published unsigned development
    prerelease `luna-v0.1.96`, installed locally with checksum verification,
    bundle version `0.1.96`, and expected ad-hoc signature.
38. Installed command down-channel smoke for `luna-v0.1.96` proved the client
    now attempts completion, but the API rejected `/complete` with a 500:
    `complete_desktop_command` compared a database-loaded lease timestamp with
    a different timezone awareness than `now`. The command therefore expired
    after lease timeout even though raw request markers were not persisted.
    Follow-up branch `codex/luna-v0196-validation` normalizes lease timestamps
    before Python comparisons and adds a regression test for naive future
    leases loaded from the database.
39. PR #801 merged the API-only backend lease-time normalization into `main`
    on 2026-06-06 UTC as merge commit `e6990445`. Post-merge broad Tests run
    `27059025321` passed, Docker Desktop Deployment run `27059025330` passed,
    and the live API returned `200` at both `https://agentprovision.com/api/v1`
    and `http://localhost:8000/api/v1`. Luna's exact Docker mount gate returned
    no output:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
40. No new Luna desktop release was expected from PR #801 because it changed
    only the API. The installed `/Applications/Luna.app` remained unsigned
    development prerelease `luna-v0.1.96` with ad-hoc signature and no
    `TeamIdentifier`. Computer Use verified the app opens expanded by default,
    remains logged in, and shows `Control Locked` with Assist/Control disabled.
    The first smoke immediately after API deploy returned `409 No connected
    desktop shell` because the deployment restarted the API's in-memory
    presence store while the already-running client still believed it was
    registered. After a clean Luna restart, the shell re-registered and the
    governed `get_active_app` smoke command
    `0dd3bb2a-d119-4e77-8580-96a356c7b529` was enqueued, claimed, and completed
    before lease expiry with status `denied`, outcomes
    `requested/started/denied`, reason
    `desktop observe locked; get_active_app denied`, and
    `marker_persisted=false`. API logs showed `/complete` returning `200` with
    no recurrence of the mixed-timezone `TypeError` or HTTP 500.
41. Luna lead release-gate review approved the PR #801 API-only gate. She
    treated the post-deploy shell re-registration issue as non-blocking and
    recommended the next phase start with native control scaffolding plus
    denial-only tests, then signed-envelope validation, then approval grant
    consumption, and only then narrow pointer/keyboard execution.
42. Branch `codex/luna-native-control-scaffold` starts that next phase without
    enabling actuation. The API command taxonomy now accepts pointer and
    keyboard scaffold actions, but enqueue records an immediate display-safe
    denied command instead of creating claimable work. Luna's client command
    executor explicitly completes any claimed native-control action as denied,
    and Tauri exposes pointer/keyboard native command stubs that all return the
    same fail-closed policy denial while `can_control_pointer` and
    `can_control_keyboard` remain false. The client also re-checks local Stop
    after native observation returns and before posting success, so an in-flight
    claimed observation cannot win a success completion after Stop latches.
43. Alpha council review for this branch could not complete as requested:
    Claude returned `Unsupported platform: claude`, and the Codex leg reviewed
    an older command-control ref because `codex/luna-native-control-scaffold`
    was not pushed yet. The stale-ref review still surfaced two real follow-up
    gates to track before live native control expands: ambient clipboard and
    activity emissions in Tauri must be disabled or routed through display-safe
    governed audit, and device-token command authority should explicitly reject
    revoked/offline `device_registry` rows instead of relying only on presence.
44. PR #803 merged the native-control scaffold into `main` on 2026-06-06 UTC
    as merge commit `40403fcf`. Alpha pushed-branch council review found no
    blocking findings in the Codex leg; Claude remained unavailable with
    `Unsupported platform: claude`. PR checks passed for API unit, API
    integration, Luna client, and aggregate status. Post-merge broad Tests run
    `27059620727`, Docker Desktop Deployment run `27059620729`, and Luna Client
    Tauri Build run `27059620724` all passed. GitHub Actions published
    unsigned development prerelease `luna-v0.1.97`; signing/notarization and
    stable updater publication were skipped as expected while development
    builds remain unsigned.
45. Installed-release validation for `luna-v0.1.97` downloaded
    `Luna_0.1.97_aarch64.dmg` plus `.sha256`, verified directly with
    `shasum -c`, installed `/Applications/Luna.app`, and confirmed bundle
    version `0.1.97`. Codesign reported an ad-hoc signature with no
    `TeamIdentifier`; `spctl` rejected the app as expected for the current
    unsigned development posture. Computer Use verified chat/session startup in
    the expanded default window, `Control Locked`, disabled Assist/Control,
    TCC Screen Recording and Accessibility denied/not-yet-granted, and then a
    local `Stop` latch with `Resume` visible. Public and local API health checks
    returned `200`; Luna's exact Docker mount gate returned no output:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
46. Installed command-channel smoke for `luna-v0.1.97` passed the scaffold
    invariants. An internal `pointer_click` command returned immediate terminal
    `denied` with capability `pointer_control`, null lease, display-safe
    `desktop_command_completed` event, and no claimable native-control work.
    Raw request marker text was absent from `desktop_commands`,
    `desktop_command_events.metadata`, and mirrored `session_events.payload`.
    An active-session `get_active_app` observation command was queued, claimed
    by the installed app, and completed `denied` with reason
    `desktop observe locked; get_active_app denied`; marker text was absent
    from command payload and event metadata. A mistakenly queued older-session
    observe command was preempted through the authenticated Stop endpoint, and
    final queue validation reported zero pending commands for the live shell.
47. PR #806 merged native-control safety hardening into `main` on 2026-06-06
    UTC as merge commit `37c6f18a`. The branch made revoked/disabled desktop
    devices fail closed during command claim and completion, added a
    `NativeControlCommandPolicy` envelope/lease/tier gate in Luna Tauri, and
    kept direct Tauri pointer/keyboard entrypoints denied because they have no
    claim lease, signed envelope, or tier context. Local validation passed
    targeted API lifecycle/binding tests, `ruff`, Rust policy tests,
    `cargo check`, Luna client JS tests, and `git diff --check`. PR CI and
    post-merge broad Tests/Docker Desktop Deployment workflows passed.
48. The post-merge Luna Client Tauri Build run `27064562475` produced unsigned
    development prerelease `luna-v0.1.98`; signing/notarization and stable
    updater manifest publication were skipped as expected for unsigned
    development builds. Installed-release validation downloaded
    `Luna_0.1.98_aarch64.dmg` plus `.sha256`, verified directly with
    `shasum -c`, installed `/Applications/Luna.app`, and confirmed bundle
    version `0.1.98`. Computer Use verified the chat/session surface, expanded
    startup window, durable `Stopped` strip, disabled Observe/Assist/Control/
    Lock/Stop controls, visible `Resume`, and Luna's Alpha Chat lead response
    in the active session. The exact Docker mount gate returned no output:
    `docker ps -q | xargs docker inspect --format '{{.Name}}{{range .Mounts}} {{.Source}}{{end}}' | grep _work`.
49. Luna Supervisor accepted lead for the next phase via Alpha Chat on
    2026-06-06. Her requested implementation order is the trust edge first:
    server-issued signed command envelopes with tenant/user/session/command/
    shell/device/policy/risk/issued/expires/nonce/action/decision fields,
    durable nonce replay denial, strict command/session/device binding,
    server-side audit events for signed/denied/expired/replayed/revoked/
    completed/stopped/policy-mismatch outcomes, and UI states that remain
    locked until a valid envelope, lease, nonce, and audit path exist. She kept
    live pointer/keyboard actuation explicitly out of scope for the first PR.
50. Branch `codex/luna-signed-envelope-gate` implements the first trust-edge
    slice without enabling native actuation: API-issued HMAC command envelopes
    are attached to claimed commands, envelope nonces are stored in
    `desktop_command_envelope_nonces`, Luna forwards the claimed envelope nonce
    on completion, and the API verifies signature, expiry, tenant/user/session/
    command/shell/device/action/capability/policy binding, and single-use nonce
    consumption before accepting completion. Missing, mismatched, tampered,
    expired, or replayed envelopes terminalize as
    `desktop_command_envelope_denied` with display-safe audit metadata. Luna
    Alpha Chat review found no blocker and accepted HMAC-only server validation
    for this fail-closed slice because pointer/keyboard remains disabled.
    Claude Code review found no blockers; its non-blocking shell-id CHECK
    watch item was closed by rejecting non-`desktop-` shell ids before command
    insert/claim nonce issuance.
51. PR #807 merged into `main` on 2026-06-06 UTC as merge commit
    `c0eb171b`. PR checks passed for API unit, API integration, and Luna client.
    Post-merge Docker Desktop Deployment run `27065232271` and broad Tests run
    `27065232265` passed. The Luna Client Tauri Build run `27065232254` built
    the unsigned ARM64 DMG and checksum but failed in the release-publication
    step after `gh release create` timed out against GitHub's API; the release
    side effect completed later and published `luna-v0.1.99` with
    `Luna_0.1.99_aarch64.dmg` and `.sha256`.
52. Installed-release validation for `luna-v0.1.99` downloaded the release DMG
    plus checksum, verified directly with `shasum -c`, installed
    `/Applications/Luna.app`, and confirmed bundle version `0.1.99`. Computer
    Use verified the installed Tauri app at `tauri://localhost`, active Luna
    Alpha Chat handoff, durable `Stopped` strip, disabled
    Observe/Assist/Control/Lock/Stop controls, visible `Resume`, and no pointer
    or keyboard actuation. The app launched expanded at `0,34 1496x885`.
    Codesign reported the expected ad-hoc unsigned development signature, and
    Luna's exact Docker `_work` mount gate returned no output.
53. Branch `codex/alpha-chat-async-send` addresses the recurrent Alpha CLI
    Cloudflare 524 path found during Luna handoff. `alpha chat send` and REPL now
    use the durable async chat-job transport: `POST /messages/start`, then
    `GET /chat/jobs/{id}/events?from_seq=N` with heartbeat-backed tails and
    sequence reconnects, instead of holding `/messages` or `/messages/stream`
    open for the full agent turn. The collector now also treats stream-open
    failures as recoverable: it polls the durable job, reconnects while the job
    is still running, and falls back to the persisted result message after job
    completion. Validation passed core parser tests, CLI tests, `cargo check`,
    and live Alpha Chat smoke; Luna accepted the update and kept `v0.1.99`
    installed-release validation as the current gate.
54. The same branch hardens the Luna release workflow against the `v0.1.99`
    delayed-release timeout: missing signing secrets are logged as notices in
    unsigned development mode, and release create/upload is now idempotent with
    retries plus a post-failure `gh release view` check before retrying or
    uploading assets. Asset upload failure still fails the workflow after
    retries, even when release creation already succeeded.
55. Operator reminder on 2026-06-06: Luna Tauri should use Alpha CLI as her
    kernel. Next implementation must add an explicit Tauri Alpha-kernel adapter
    plan before native actuation expands: discover/pin the `alpha` binary,
    bridge auth/session context, stream chat-job output into Luna UI, surface
    cancel/stop semantics, and keep desktop command execution governed through
    signed API envelopes rather than direct CLI-side actuation.
56. Operator scope update on 2026-06-06: native app/window monitoring should
    focus on macOS only for now. Do not implement Windows native monitoring or
    actuation in the next phase. Keep API field names neutral enough to avoid
    future rewrites, but gate implementation, tests, release smoke, and Tauri
    UX around macOS app/window state first.
57. PR #808 merged into `main` on 2026-06-06 UTC as merge commit `92f056bc`.
    PR checks passed for Alpha CLI Build Matrix and Tests. The branch delivered
    durable async Alpha Chat transport, stream-open recovery, idempotent Luna
    release create/upload retries, and the explicit Alpha CLI kernel constraint
    for Luna Tauri.
58. Luna Supervisor acknowledged the macOS-only Alpha-kernel direction through
    Alpha Chat on 2026-06-06 with no blocker. Her guardrail: keep capability
    advertising conservative until Alpha CLI/core, Tauri, audit, and approval
    behavior are present together. Do not make API-only promises ahead of local
    kernel support.
59. Post-merge validation for PR #808 passed on merge commit `92f056bc`: broad
    Tests, CLI Build Matrix, Docker Desktop Deployment, and Luna Client Tauri
    Build all completed successfully. GitHub Actions published unsigned
    development prerelease `luna-v0.1.100`; the DMG and `.sha256` were
    downloaded, `shasum -c` verified the checksum, `/Applications/Luna.app`
    reported bundle version `0.1.100`, and codesign reported the expected
    ad-hoc signature with no `TeamIdentifier`.
60. Computer Use smoke on installed `luna-v0.1.100` verified the expanded
    chat/session surface, visible Luna Alpha Chat handoff, durable `Stopped`
    safety strip, disabled Observe/Assist/Control/Lock/Stop while stopped,
    visible `Resume`, and passive TCC readiness with Screen Recording and
    Accessibility denied/not-yet-granted. Luna's exact Docker `_work` mount
    gate returned no output.
61. Branch `codex/luna-macos-alpha-kernel` implements the first macOS-only
    local-kernel/readiness slice without API expansion or native actuation:
    Luna Tauri now reports Alpha CLI discovery status in the control safety
    state, exposes a local `alpha_kernel_status` command, reports macOS
    app-monitor readiness from mode plus Accessibility status, and keeps
    capability advertising conservative. Active-app policy now gates on
    Accessibility only; passive System Events automation remains visible in TCC
    readiness and runtime failures still audit/deny. The ambient activity
    tracker now emits metadata-only app-switch events and no longer forwards
    raw window titles, subprocess args, terminal cwd, or project labels.
62. Local branch debug-app smoke built an unsigned `Luna.app` from
    `codex/luna-macos-alpha-kernel`, temporarily installed it into
    `/Applications`, and verified with Computer Use that the safety strip showed
    `Stopped Alpha OK Mac Stopped` while Assist/Control and pointer/keyboard
    actuation remained disabled. After the branch smoke, `/Applications/Luna.app`
    was restored to verified release `luna-v0.1.100` with checksum validation.
63. Council review found one privacy blocker before PR: after ActiveApp moved to
    Accessibility-only gating, direct Tauri `get_active_app` still returned raw
    `title`. The branch now fixes that path too: direct active-app results are
    metadata-only (`app`, `title_present`, `title_chars`), Command Palette
    includes only app name in prompt context, and the API safe `result_fields`
    allowlist no longer accepts raw `title`.
64. Council re-review after the fix found no remaining blockers. Luna final
    Alpha Chat review was requested with the post-fix validation summary, but
    the durable Alpha Chat job did not return an ACK during this turn; no
    hanging local Alpha CLI process remained after cleanup.
65. PR #810 merged into `main` on 2026-06-06 UTC as merge commit `a0f88f44`.
    Post-merge broad Tests, Docker Desktop Deployment, and Luna Client Tauri
    Build all passed. GitHub Actions published unsigned development prerelease
    `luna-v0.1.101`; the DMG and `.sha256` were downloaded, `shasum -c`
    verified the checksum, `/Applications/Luna.app` reported bundle version
    `0.1.101`, and codesign reported the expected ad-hoc signature with no
    `TeamIdentifier`. Computer Use verified the expanded chat/session UI,
    safety strip `Stopped Alpha OK Mac Stopped`, disabled Observe/Assist/
    Control/Lock/Stop, visible `Resume`, and no pointer/keyboard actuation.
    Luna's exact Docker `_work` mount gate returned no output.
66. The CLI Alpha Chat path still returned a Cloudflare HTML error for this
    handoff (`400 Bad Request`), so the Luna release-gate and next-slice
    context was sent through the installed Luna app's Alpha Chat UI with
    Computer Use. Luna ACKed the gate, found no blocker to
    `codex/luna-v0101-approval-trust`, and approved proceeding with local
    claimed-envelope preflight before any native invoke while keeping
    pointer/keyboard disabled. Her guardrail: claimed envelopes must fail
    closed on missing/expired/replayed/revoked claims, bind to tenant/user/
    session/shell/device/command, and produce audit-only outcomes until
    approval trust is proven.
67. PR #811 merged into `main` on 2026-06-06 UTC as merge commit `de169085`.
    Post-merge broad Tests, Docker Desktop Deployment, and Luna Client Tauri
    Build all passed. GitHub Actions published unsigned development prerelease
    `luna-v0.1.102`; the DMG and `.sha256` were downloaded, `shasum -c`
    verified the checksum, `/Applications/Luna.app` reported bundle version
    `0.1.102`, and codesign reported the expected ad-hoc signature with no
    `TeamIdentifier`. Computer Use verified `Stopped Alpha OK Mac Stopped`,
    disabled Observe/Assist/Control/Lock/Stop controls, visible `Resume`, no
    native actuation, and expanded window geometry `0,34 1496x933`. Luna's
    exact Docker `_work` mount gate returned no output.
68. Luna Supervisor ACKed the `v0.1.102` installed-release gate through the
    installed Luna app's Alpha Chat. She approved continuing macOS-only from
    the next gated slice while keeping pointer/keyboard actuation disabled,
    watching for Alpha CLI/core versus API mismatches, claim validation that
    does not fail closed, and UI states that imply control before native invoke
    is gated.
69. Branch `codex/luna-v0102-validation-next` adds the macOS app-monitor
    event-contract hardening slice: Rust emits versioned
    `agentprovision.macos_app_monitor_event.v1` metadata-only app-switch
    envelopes with event id, observed timestamp, context hash, app labels, and
    coarse title presence/count; React sanitizes those events before API
    forwarding or local UI dispatch; the API `/activities/track` endpoint also
    requires a UUID `event_id` for v1 monitor events and strips raw
    `window_title` and `subprocess` values before writing `user_activities`.
    Raw window titles, subprocess args, clipboard values, paths, and screenshot
    pixels remain out of the monitor payload, and native pointer/keyboard
    actuation remains disabled.
70. PR #812 merged into `main` on 2026-06-06 UTC as merge commit `dc2e4257`.
    Post-merge broad Tests, Docker Desktop Deployment, and Luna Client Tauri
    Build all passed. GitHub Actions published unsigned development prerelease
    `luna-v0.1.103`; the DMG and `.sha256` were downloaded, `shasum -c`
    verified the checksum, `/Applications/Luna.app` reported bundle version
    `0.1.103`, and codesign reported the expected ad-hoc signature with no
    `TeamIdentifier`. Computer Use verified expanded chat/session startup at
    `0,38 1728x1079`, `Stopped Alpha OK Mac Stopped`, disabled Observe/
    Assist/Control/Lock/Stop controls, visible `Resume`, and no native
    actuation. Luna's exact Docker `_work` mount gate returned no output.
71. Luna Supervisor ACKed the `v0.1.103` installed-release gate through the
    installed Luna app's Alpha Chat. She approved continuing from the next
    gated phase and named the highest-priority blocker before native actuation:
    claim authenticity and replay resistance at the local native boundary.
    Every action must come from a fresh, signed, correctly scoped approval
    envelope with replay/revocation checks before any native call. Pointer and
    keyboard remain disabled.
72. Branch `codex/luna-alpha-kernel-adapter` starts the approval trust boundary
    slice: explicit `desktop_command_approval_grants` records, an internal
    grant-creation endpoint, claim-time database compare-and-swap consumption,
    approval identity/risk binding in signed command envelopes, Luna client
    preflight denial for missing or mismatched approval metadata, and
    display-safe denial/audit behavior when commands lack usable grants.
    Council review found three issues and the branch now addresses them:
    grantless commands remain pending/claim-empty until approval or TTL instead
    of being terminally denied before a command-bound grant can be created;
    Stop revokes active session/shell/device approval grants; and command-bound
    approval grants have database FK plus active-grant uniqueness constraints.
    The client preflight now requires top-level command, payload approval, and
    envelope approval IDs to match exactly.
73. Luna Supervisor ACKed the branch through the installed Luna app's Alpha
    Chat and found no blocker before opening the PR, with the explicit framing
    that this is trust-boundary plumbing and not native actuation enablement.
    Pre-PR Computer Use smoke on installed `/Applications/Luna.app` version
    `0.1.103` verified the live shell remains responsive: `Resume` moved from
    `Stopped Alpha OK Mac Stopped` to `Control Locked Alpha OK Mac Locked`,
    `Observe` moved to `Observe Alpha OK Mac Denied` while macOS Screen
    Recording/Accessibility were denied, Assist and Control stayed disabled,
    and `Stop` returned the app to `Stopped Alpha OK Mac Stopped`.
74. PR #813 merged into `main` on 2026-06-06 UTC as merge commit `a91b9048`.
    Main broad Tests, Docker Desktop Deployment, and Luna Client Tauri Build
    all passed. GitHub Actions published unsigned development prerelease
    `luna-v0.1.104`; the DMG and `.sha256` were downloaded, `shasum -c`
    verified the checksum, `/Applications/Luna.app` reported bundle version
    `0.1.104`, and codesign reported the expected ad-hoc signature with no
    `TeamIdentifier`. Luna's exact Docker `_work` mount gate returned no
    output. Computer Use verified the installed app opens authenticated on the
    chat/session surface, starts in `Stopped Alpha OK Mac Stopped`, transitions
    `Resume -> Control Locked Alpha OK Mac Locked`, transitions `Observe ->
    Observe Alpha OK Mac Denied` with Screen Recording/Accessibility denied as
    expected, keeps Assist and Control disabled, and `Stop` relatches to
    `Stopped Alpha OK Mac Stopped`.
75. Current branch `codex/luna-native-boundary-proof` adds a first-use
    permission-onboarding slice before deeper native-boundary work. The
    existing `TCC` readiness panel remains passive on launch, but denied or
    unknown rows now expose explicit `Enable`/`Open` actions. Clicking an
    action calls a native `control_open_permission_setup` command that opens
    the scoped macOS Privacy & Security pane for only that permission
    (`Screen Recording`, `Accessibility`, `Automation`, `Input Monitoring`,
    `Camera`, or `Microphone`); Screen Recording also asks macOS to present the
    standard capture-access prompt when available. This makes Luna behave more
    like Codex Desktop for first-run setup without silently changing OS
    privacy settings or enabling pointer/keyboard actuation.
76. Follow-up finding from local validation: macOS TCC grants are scoped to the
    currently running code identity, not just the display name. With unsigned
    ad-hoc development builds, `/Applications/Luna.app` and a branch debug
    bundle can both display as `Luna` and use bundle ID `com.agentprovision.luna`
    while codesign reports different ad-hoc identifiers (for example
    `luna-525c10c19781945d` versus `luna-27be493139265cb6`). That explains
    the confusing state where System Settings appears to show Luna fully
    allowed but the active branch process still reports Screen/AX denied. The
    TCC modal must show the running app bundle path, bundle ID, ad-hoc
    signature identifier, and a TCC-scope note so users know which Luna entry
    macOS is evaluating. A local copy re-signed with
    `codesign --sign - --identifier com.agentprovision.luna` still produced a
    designated requirement based on `cdhash`, so an explicit ad-hoc identifier
    is not enough to guarantee TCC continuity between builds. While development
    remains unsigned/ad-hoc, permission-state diagnostics must be explicit; the
    durable fix for update-to-update TCC continuity is Developer ID signing when
    the project is ready to re-enable it.
77. Developer ID release signing setup was created on 2026-06-06 for Luna:
    certificate ID `W5K3DXA7TD`, subject `Developer ID Application: Simon
    Aguilera (KF9LPYY7KK)`, Team ID `KF9LPYY7KK`, G2 issuer, expiration
    `2031-06-07`, SHA256 fingerprint
    `A0:BF:89:39:3D:7C:AC:07:8B:0A:42:35:19:F2:50:2F:62:9C:88:28:04:29:6E:BC:0E:CD:DB:F9:22:1B:ED:F4`.
    The private key, `.p12`, updater signing key, and generated passphrases
    live outside the repo under `~/Documents/LunaSigning` with owner-only file
    permissions. GitHub Actions secrets are configured for
    `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_ID`,
    `APPLE_PASSWORD`, `APPLE_TEAM_ID`, `TAURI_SIGNING_PRIVATE_KEY`, and
    `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. The client updater public key was
    rotated in `apps/luna-client/src-tauri/tauri.conf.json`; therefore the
    first signed build containing this new public key must be manually
    installed from its DMG before automatic updater continuity can be validated
    for later releases.
78. Review and validation status for the current release-signing/permission
    onboarding slice: Luna Supervisor reviewed through Alpha Chat and reported
    no blocker before the PR/CI signed-build gate, with the explicit caveat
    that updater continuity remains pending until the first rotated-key signed
    build is manually installed from DMG. Codex local review found no
    permission-counting, setup-command, or native-actuation regression. Claude
    Code print mode answered a tiny health-check prompt, but both Opus/max and
    Sonnet substantive read-only review prompts hung without output and were
    terminated; do not treat Claude review as completed for this pass.
79. First signed-mode CI attempt on branch `codex/luna-native-boundary-proof`
    failed in `cargo tauri build` while importing the PKCS#12 certificate:
    `SecKeychainItemImport: MAC verification failed during PKCS12 import`. Local
    reproduction showed OpenSSL could read the file, but macOS `security import`
    rejected it. The certificate was regenerated from the same Developer ID cert
    and private key using an Apple-compatible legacy PKCS#12 format, verified
    locally with a temporary keychain, and `APPLE_CERTIFICATE` plus trimmed
    `APPLE_CERTIFICATE_PASSWORD` were re-uploaded to GitHub Actions secrets.
80. After the Apple-compatible PKCS#12 fix, CI imported the Developer ID
    identity but codesign failed with `unable to build chain to self-signed root
    for signer`. The Luna workflow now installs Apple's official Developer ID
    G2 intermediate certificate into the self-hosted runner login keychain before
    `cargo tauri build`, so the signer chain can be resolved during CI signing.
81. Signed-mode CI run `27071333346` cleared certificate import and codesign:
    the Luna app, native binary, and `libluna_hand_landmarker.dylib` were signed
    with `Developer ID Application: Simon Aguilera (KF9LPYY7KK)`. The run then
    failed at notarization with Apple HTTP 401: Apple requires an app-specific
    password generated at `appleid.apple.com`; the normal Apple account password
    cannot be used as `APPLE_PASSWORD` for Tauri notarization.
82. Notarization root cause + CI redesign (2026-06-06, after the app-specific
    password was uploaded). Signed branch run `27071762194` reached Apple's
    notary service but never returned: Tauri ran `notarytool submit --wait`
    inside `cargo tauri build` and slept. Diagnosis via the validated local
    keychain profile (`luna-notary-local`) showed the queue, not Luna, was the
    problem — `xcrun notarytool history` reported BOTH Luna submissions
    (`15e4f6e5…` 19:23Z, `c7d2cc34…` 19:32Z) AND a tiny independently-signed
    probe app (`7a9120cc…`, `LunaNotaryProbe.zip`, 20:07Z) all stuck
    `In Progress` 45–60+ min later (checked 20:16Z). A minimal probe stuck
    identically to Luna proves the blocker is Apple notary-service backlog, not
    app size or certificate corruption (the Developer ID cert/key/P12 had already
    validated: fingerprint `A0:BF:89…ED:F4`, valid 2026-06-06→2031-06-07). No
    code makes Apple faster, so CI was rebuilt to SURVIVE the backlog rather than
    block on it. Key correctness fact established by reading
    `tauri-bundler-2.9.2`/`tauri-macos-sign-2.3.4`: Tauri notarizes the app and
    staples it BEFORE building the DMG (so the DMG normally carries a stapled
    app), it authenticates notarytool only via Apple-ID-password (`--apple-id
    --password --team-id`, password on the long-lived `--wait` argv) or App Store
    Connect API key (`APPLE_API_KEY`/`APPLE_API_ISSUER`/`APPLE_API_KEY_PATH`, no
    password) — there is NO keychain-profile support — and `--skip-stapling`
    switches Tauri to `submit --no-wait` (returns the submission id immediately,
    no staple). Also: notarization is keyed on the code cdhash and stored
    server-side; stapling only caches the ticket locally, so once a submission is
    Accepted EVERY copy of that exact app (DMG, updater tarball) passes Gatekeeper
    online — only offline `stapler validate` needs a locally-stapled copy.
83. Redesigned `.github/workflows/luna-client-build.yaml` to an explicit,
    observable, queue-decoupled notarization pipeline (req-2/req-3 of the
    operator handoff). (a) `cargo tauri build` now signs ONLY — the Apple-ID and
    API-key env vars are withheld so tauri-bundler signs the app+dylib and skips
    notarization. (b) A new `Notarize` step imports the Developer ID identity into
    a disposable, run-scoped keychain (kept off the global search list; used later
    to sign the rebuilt DMG), sets up notary auth preferring an App Store Connect
    API key and otherwise seeding a keychain profile from the app-specific
    password via `notarytool store-credentials` (the password reaches a process
    argument ONLY there, for a few seconds — never during the poll, vs Tauri's
    ~hour-long `submit --wait`), `ditto --sequesterRsrc` zips the app, `notarytool
    submit --no-wait` captures the submission id, then a bounded poll of
    `notarytool info` runs: `Accepted`→staple and continue; `Invalid`/`Rejected`
    →`notarytool log` and fail; past `NOTARY_TIMEOUT_SECONDS` (default 1800,
    overridable via `workflow_dispatch` input/`vars`, validated to a numeric
    [60,7200])→mark `pending` and exit 0 so signed smoke artifacts still upload.
    (c) Still on the same step (so the keychain + notary auth stay in scope), once
    the app is Accepted+stapled the DMG is recreated from the now-stapled app via
    `hdiutil` + `codesign` so a dragged-out `/Applications/Luna.app` carries the
    ticket and offline `stapler validate` passes, then the DMG itself is
    notarized+stapled through the same bounded poll so a downloaded DMG opens
    without a Gatekeeper prompt; the updater `Luna.app.tar.gz`+`.sig` is left
    untouched (same cdhash → notarized online once Accepted; no re-sign needed,
    updater integrity preserved). (d) `Verify` re-checks codesign on the app and
    asserts offline Gatekeeper (`stapler validate` + `spctl --ignore-cache -t
    exec`) on the app inside the mounted rebuilt DMG — the copy users actually
    receive. (e) Publication — the
    signed GitHub Release and the stable `luna-latest` updater manifest — is now
    gated on `notarized == 'accepted'` AND (`main` or `luna-v*`); the unsigned
    dev-prerelease path is preserved; branch/PR/`workflow_dispatch` builds and
    `pending` builds never publish. Decision on req-3: we go beyond Tauri
    `--skip-stapling` — Tauri does no notarization at all and the explicit step
    owns submit/poll/staple, which is the only way to also fix the
    password-on-argv exposure (Tauri cannot use a keychain profile) and to fetch
    the failure log. Validated locally: `actionlint` clean, `bash -n` on all run
    blocks + a control-flow simulation under the runner's real bash 3.2.57,
    `hdiutil` create/attach/detach mechanics, `base64 --decode` + `find-identity`
    field layout; a 4-lens adversarial agent review (secrets, bash-3.2, signing
    semantics, CI gating) with per-finding verification whose five confirmed
    IMPORTANTs (jq-parse abort under pipefail, timeout-input validation, the
    un-notarized DMG, mounted-copy Gatekeeper assertion, and the cert-password
    argv threat-model note) were all fixed. Still PENDING on Apple:
    a fully Accepted run, the rebuilt-DMG install smoke (`codesign -dv`,
    `stapler validate`, `spctl`), and first stable-updater publication — finalize
    once Apple's queue drains (re-run the signed build; the poll completes fast on
    a healthy queue). Follow-up to fully retire the brief password exposure:
    create an App Store Connect API key and add `APPLE_API_KEY` (base64 .p8),
    `APPLE_API_KEY_ID`, `APPLE_API_ISSUER` secrets — the workflow already prefers
    them when present.
84. Runner codesign regression surfaced while validating entry 83 (2026-06-06
    ~21:15Z). Two `workflow_dispatch` validation runs on the redesigned workflow
    (`27073858932`, `27074079154`) proved the new structure behaves correctly —
    compile finished in ~1 min, the new Notarize/Verify/publish steps were gated
    and skipped as designed, and the always() keychain cleanup ran — but BOTH
    failed inside `cargo tauri build` at Tauri's OWN code-signing of
    `libluna_hand_landmarker.dylib` with `codesign: errSecInternalComponent`
    ("replacing existing signature" → errSec on the first dylib). This is NOT
    caused by the notarization redesign (that change only withholds the
    notarization credentials so Tauri signs-but-skips-notarize; signing itself is
    unchanged and was unaffected). Diagnosis on the runner (this machine, same
    user): `codesign --sign "Developer ID Application: Simon Aguilera
    (KF9LPYY7KK)"` against the ESTABLISHED key (the identity lives in
    `~/Documents/LunaSigning/luna-notary-local.keychain-db`, in the user search
    list — the login keychain itself holds 0 codesigning identities) SUCCEEDS,
    while Tauri's pattern of importing `APPLE_CERTIFICATE` into a FRESH per-build
    temp keychain (create→unlock→import→`set-key-partition-list`→`codesign
    --keychain`) FAILS. Initial hypothesis (degraded securityd after sleep) was
    WRONG — restarting the runner LaunchAgent
    (`actions.runner.nomad3-servicetsunami-agents.macbook-local`, PID 1569→21709)
    did NOT fix it.
85. CONFIRMED root cause + fix for the entry-84 codesign failure (2026-06-06
    ~21:27Z): a DUPLICATE Developer ID Application identity in the runner's user
    search list. The debugging session that diagnosed entry 82 created
    `~/Documents/LunaSigning/luna-notary-local.keychain-db` (to hold the
    `luna-notary-local` notarytool profile) and added it to the user keychain
    search list; it holds a second copy of the same Developer ID identity. It did
    not exist at the last good build (19:30Z), appeared ~20:00Z, and broke every
    build after. When Tauri runs `codesign --keychain <temp> --sign "Developer ID
    Application: …"`, the duplicate identity reachable via the search list yields
    `errSecInternalComponent`. Removing the keychain from the search list
    (`security list-keychains -d user -s ~/Library/Keychains/login.keychain-db`)
    immediately fixed signing: run `27074342545` (search list = login only)
    compiled, **signed successfully**, and proceeded into the explicit Notarize
    step exactly as designed. The keychain FILE is left in place (the prior
    session's notarytool profile is still usable by explicit `--keychain <path>`);
    only the search-list entry was removed. Operational rule: keep ad-hoc
    Developer-ID-bearing keychains OUT of the runner's user search list — access
    notary creds by explicit path. The redesign (467560f3) is now validated
    through signing + the explicit notarize submit/poll on real CI; full
    notarized-release validation (the `accepted` path: stapled-DMG install +
    `stapler validate`/`spctl`, first `luna-latest` publish) still awaits Apple's
    notary-queue backlog draining (entry 82) — re-run `gh workflow run
    luna-client-build.yaml --ref codex/luna-native-boundary-proof` (default
    1800s poll) once the queue is healthy.
86. Signed Luna `0.1.105` local TCC validation found the next permission
    onboarding gap. `/Applications/Luna.app` now has stable Developer ID
    identity `com.agentprovision.luna | team KF9LPYY7KK`, but old ad-hoc Luna
    grants can leave System Settings showing a misleading enabled `Luna` row
    while Apple's live preflight still returns denied for the running signed
    app. The local host reset Luna-scoped TCC decisions with
    `tccutil reset All/ScreenCapture/Accessibility/AppleEvents/Camera/Microphone/ListenEvent com.agentprovision.luna`;
    after relaunch, clicking Luna's Screen `Enable` button registered the
    current signed app in `Screen & System Audio Recording`, and after explicit
    user approval plus relaunch/focus refresh Computer Use verified Luna now
    reports `TCC 3/3` with Screen Recording `granted`, Accessibility `granted`,
    and Input Monitoring `not_required`; after relaunch, Automation/System
    Events also resolved to `granted` and the installed app showed `TCC 4/4`.
    Luna remained `Stopped Alpha OK Mac Stopped` with Assist/Control disabled.
    Product
    implication: setup buttons must trigger native macOS prompt APIs where
    available before deep-linking to Settings, and the UI must repoll readiness
    when Luna regains focus after the user returns from System Settings. This
    branch now adds Accessibility prompt registration via
    `AXIsProcessTrustedWithOptions`, asks Automation/System Events with
    `AEDeterminePermissionToAutomateTarget(..., ask_user_if_needed=true)`, and
    refreshes permission readiness on focus/visibility changes. This remains
    setup-only: it cannot and must not silently grant OS permissions or unlock
    Assist/Control.
87. Follow-up Computer Use smoke after Screen/AX were granted reached
    `Control Locked Alpha OK Mac Locked`, then `Observe Alpha OK Mac Ready`
    with Assist/Control still disabled and no pointer/keyboard actuation.
    Pressing Stop wrote the durable `desktop-control-stop` latch before any
    secondary teardown, but the current installed WebView stayed visually in
    Observe with the Stop button disabled until app relaunch; relaunch restored
    `Stopped Alpha OK Mac Stopped`, proving the native latch was authoritative
    and the UI was stale. The branch now adds a WebView-side Stop fallback:
    pressing Stop immediately publishes an optimistic stopped posture, clears
    local control affordances, and times out a slow native Stop invoke instead
    of leaving the UI in Observe. This does not weaken safety because native
    Stop already persists the latch before gesture teardown; it only makes the
    visible state fail closed when the bridge is slow. Luna re-review later
    tightened this: the UI must not claim `Stopped` until native
    `control_stop_all` returns or a confirmed safety refresh reports the Stop
    latch. The branch now shows a disabled `Stopping` posture during pending
    native confirmation; `Stopped` is published only from native state.
88. Luna Supervisor reviewed entry 86/87 via Alpha Chat and accepted the branch
    framing as TCC readiness plus Stop fail-closed UX hardening only. Her merge
    condition remains unchanged: review must confirm the patch does not add any
    native pointer, keyboard, Assist, or Control execution path. Native
    actuation stays blocked until approval-envelope authenticity, replay
    defense, revocation, session/device/command binding, and denial audit gates
    are proven at the native boundary.
89. Native-boundary proof slice added on `codex/luna-native-boundary-proof`.
    Native pointer/keyboard claims now pass through a proof-only Tauri command
    before terminal command completion. Valid-looking claims run JS preflight
    first and then the Rust proof; malformed native-control claims also call the
    Rust proof when possible, so missing/malformed envelopes are rejected at the
    native boundary rather than only in the WebView. The Rust boundary
    independently rejects missing envelopes, malformed/unsigned envelopes,
    expired envelopes, replayed nonces, revoked grants, wrong shell/session/
    device/command bindings, and approval grant mismatches; it emits
    `desktop_native_control_denied` display-safe audit metadata and returns a
    structured denial result to the claim loop.
    The proof still sets `tier_enabled=false`, so even a valid native-control
    envelope completes as `desktop native control tier disabled` and no
    `control_pointer_*` or `control_keyboard_*` macOS path is invoked. Local
    validation passed `cargo fmt --check`, `cargo check`, `cargo test`, `npm
    test -- ControlSafetyStrip.test.jsx --run`, `npm test --
    useDesktopCommandClaims.test.jsx --run`, `npm run build`, and `git diff
    --check`. Remaining caveat: cryptographic verification is not implemented
    in this slice; Rust checks envelope metadata plus signature presence, while
    API-side HMAC signing remains the current server verifier.
90. Mainline PR #817 merged `docs/plans/2026-06-06-grounded-agentprovision-pattern.md`
    as merge `3442a3fe`, adding the claim ledger, assumption firewall,
    grounding statuses, desktop-native grounding surface, and PR ladder. The
    Luna computer-use plan should now treat native-control envelope proofs as
    evidence contracts: denial audit events and future approval-verifier traces
    must be joinable to claim/action provenance, missing checks, risk posture,
    and operator-visible grounding state. The next native-control work should
    align with the grounded plan's sequence: measure/trace first, enforce next,
    and only then consider canary actuation.
91. PR #816 signed smoke artifact validation on branch head `e2e652d5`
    completed with CI run `27077213653`. The branch Tests run `27077174348`
    passed, and Luna Client Tauri Build signed version `0.1.105` with Developer
    ID team `KF9LPYY7KK`, then uploaded artifact `7459146318`. Apple's notary
    service kept submission `c94a2cab-b871-456a-bf95-6adc0c60f131`
    `In Progress` for the full 1800-second poll, so the workflow intentionally
    emitted signed un-stapled smoke artifacts only: `Verify signing,
    notarization, and stapled DMG`, updater manifest generation, release
    publication, and `luna-latest` publication were skipped. Local smoke
    installed the uploaded DMG into `/Applications/Luna.app` after checksum
    verification; the installed bundle is `com.agentprovision.luna` version
    `0.1.105`, CDHash `d7af69145fc45eb6c17a76480f220a26c1b7b0a8`, signed by
    `Developer ID Application: Simon Aguilera (KF9LPYY7KK)`. Expected pending
    notary state was confirmed: `stapler validate` reports no ticket and
    `spctl` rejects as `Unnotarized Developer ID`. Computer Use verified the
    smoke build launches authenticated, opens expanded at `0,34 1496x933`,
    reports running identity `com.agentprovision.luna | team KF9LPYY7KK`, shows
    Screen/AX granted, resolves Events granted after Stop, reaches `TCC 4/4`,
    and preserves the safe flow `Stopped -> Control Locked -> Observe Alpha OK
    Mac Ready -> Stopped` with Assist/Control disabled and no pointer/keyboard
    actuation. Luna's exact Docker `_work` mount gate returned no output. This
    validates the signed smoke artifact and local TCC/safety behavior, but it
    does NOT close the signed/notarized release gate; that remains blocked on an
    Accepted/stapled run and first updater/release publication.
92. Luna Supervisor reviewed the entry-91 packet in Alpha Chat from the
    installed signed smoke build. She fetched
    `origin/codex/luna-native-boundary-proof` and verified remote head
    `e2e652d5b27349b11e12132028c33206e3735f0e`. Her blocker-focused result:
    PR #816 is acceptable to keep PR-ready/review-ready as the native-boundary
    proof slice, with the notarized-release gate still open. She found no
    code-level proof-boundary blocker: `control_prove_native_command_boundary`
    exists and is proof/audit-only; pointer/keyboard Tauri commands still route
    to denial-only policy; `desktop_control_allows_actuation()` remains hard
    false; `tier_enabled=false` still blocks native control after a
    valid-looking claim; the Stop truth issue appears fixed by `Stopping`
    pending state plus native/refreshed `Stopped`; Rust rejects missing,
    malformed, expired, replayed, revoked, wrong-binding approval/envelope
    cases; and the React claim path does not invoke `control_pointer_*` or
    `control_keyboard_*` for native-control claims. Her exact remaining blocker
    is release-only: do not call the work release-complete until notarization,
    stapling, updater/release artifact verification, local install smoke, and
    `spctl` pass. She also called out the known proof-slice caveat as
    acceptable only while explicit in the PR: Rust validates envelope metadata,
    signature presence, replay, revocation, and bindings, but does not yet
    perform cryptographic public-key verification.
93. PR #816 body was updated with the native-boundary proof scope, signed smoke
    artifact validation, explicit non-cryptographic verifier caveat, and the
    pending notarized-release gate. After Luna's entry-92 review result, PR #816
    was marked ready for review and then merged to `main` as
    `e072f8bfa66d82e27ce3d411e252176e4193fea9` at
    `2026-06-07T01:11:30Z`. Main Tests run `27078867670` passed, Docker
    Desktop Deployment `27078867674` passed, and Luna's exact Docker `_work`
    mount gate returned no output. Main Luna Tauri Build `27078867671` signed
    version `0.1.105` with Developer ID team `KF9LPYY7KK` and uploaded smoke
    artifact `7459705203`; Apple notarization submission
    `4669ea06-7a4c-4399-be3b-b88817e40d3d` stayed `In Progress` for the full
    1800-second poll, so the workflow intentionally uploaded signed un-stapled
    smoke artifacts only and did not publish `luna-v0.1.105` or `luna-latest`.
    Local install from artifact `7459705203` verified `/Applications/Luna.app`
    version `0.1.105`, CDHash `126962e00065dac4501855330f2505acd463e25d`,
    TCC `4/4`, expanded bounds `0,34,1496,933`, and safe Computer Use flow
    `Stopped -> Resume -> Control Locked -> Observe -> Mac Ready -> Stop ->
    Stopped`, with Assist/Control disabled and no pointer/keyboard actuation.
    Luna Supervisor acknowledged the merge and held only the release-complete
    gate open: do not mark `0.1.105` release-complete until Apple accepts
    notarization, app+DMG stapling passes, `spctl` passes, updater/release
    publication completes, and local install from the notarized DMG passes.
94. Branch `codex/luna-native-envelope-crypto` starts the next native-boundary
    phase from `origin/main`. It adds an opt-in API Ed25519 command-envelope
    issuer/verifier while preserving the current HMAC default for compatibility.
    The API uses `DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM=Ed25519` plus a
    base64url/hex 32-byte `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY` to
    issue `signature_alg=Ed25519` / key id
    `agentprovision-desktop-command-ed25519-v1`; completion verification now
    accepts both HMAC and Ed25519 and rejects tampered Ed25519 payloads. Luna
    Tauri now preserves raw envelope JSON, removes only `signature` for
    canonical verification, requires Ed25519 + the expected key id for native
    pointer/keyboard proof requests, verifies against
    `LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY` (runtime or compile-time
    env), and still feeds the verified envelope into the existing policy with
    `tier_enabled=false`, so successful verification still terminates as
    `desktop native control tier disabled` and never reaches macOS actuation.
    React preflight keeps observe commands compatible with HMAC or Ed25519, but
    routes HMAC native-control claims through the Rust proof denial path. Local
    validation passed `cargo fmt --check`, `cargo check`, `cargo test`, `npm
    test -- useDesktopCommandClaims.test.jsx --run`, `npm run build`, `pytest
    tests/api/v1/test_desktop_command_lifecycle.py -q`, `ruff check
    app/services/desktop_control_service.py app/core/config.py
    tests/api/v1/test_desktop_command_lifecycle.py`, and `git diff --check`.
    Luna Supervisor, Claude Code Desktop Superpowers review, and Codex review
    all kept the slice blocked until Rust canonicalization matched the API's
    `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
    Ed25519 signing contract. Commits `23aadffe` and `8b08dc5e` fixed the
    native verifier to remove only top-level `signature`, recursively sort JSON
    object keys, ASCII-escape non-printable/non-ASCII strings including `U+007F`,
    and prove signature verification is independent of received JSON key order.
    Fresh parent-branch validation passed `cargo fmt --check`, `cargo check`,
    `cargo test`, and `git diff --check`. Native actuation remains disabled.

---

## Goals

1. Make `main` chat/sessions the primary Luna Tauri surface.
2. Demote `spatial_hud` to an opt-in Labs/Presence surface.
3. Stop camera/gesture startup unless the user explicitly enables a feature
   that requires it.
4. Add a governed local computer-use actuator in Tauri:
   - screenshot
   - macOS active app/window context and native app monitor state
   - clipboard read/write
   - pointer move/click
   - keyboard typing / key chords
   - local stop/pause
5. Route decisions through AgentProvision with Alpha CLI as Luna's local kernel:
   - Luna Tauri -> `alpha` CLI -> AgentProvision chat/task/router -> MCP/API
     authorization and audit -> desktop command envelope
   - Tauri executes only approved, scoped action envelopes as the native actuator
6. Extend Alpha CLI/core alongside any API extension Luna depends on:
   - typed request/response models
   - commands or library calls usable by the Tauri shell
   - streaming/cancel/error semantics compatible with Luna UI
7. Persist an authoritative replayable audit trail in desktop-control tables and
   mirror display-safe rows into `session_events`.
8. Enforce tenant, user, session, shell/device, and capability scoping on every
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
7. Do not implement Windows native app monitoring or Windows actuation in the
   next phase; macOS is the only native platform target until this plan is
   explicitly reopened for Windows.

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
9. Tauri updater private keys and Apple Developer certificate material must
   stay outside the repository and flow into CI only through GitHub Actions
   secrets. The app embeds only the updater public key.

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
  "capability": "pointer_control",
  "risk_tier": "native_control",
  "approval_id": "uuid",
  "approval_risk_tier": "native_control",
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
    "risk_tier": "native_control",
    "capability": "pointer_control",
    "approved_by_user_id": "uuid",
    "approved_at": "2026-06-05T00:00:00Z",
    "expires_at": "2026-06-05T00:00:10Z",
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
7. Missing macOS TCC permissions have direct, scoped setup buttons that open the
   correct System Settings pane from Luna instead of leaving users to hunt
   through Privacy & Security manually.

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
- [x] Developer ID signing material created for Luna on 2026-06-06 and stored
      outside the repo under `~/Documents/LunaSigning`; CI secrets now include
      the Apple certificate, certificate password, Apple ID, Apple notarization
      password, Team ID, Tauri updater private key, and updater-key password.
- [x] Rotate the Luna Tauri updater public key in `tauri.conf.json` to match
      the newly generated updater private key configured in GitHub Actions.
- [ ] First signed-release validation after updater-key rotation: build from
      GitHub Actions, confirm CI enters signed mode, notarization/stapling pass,
      `latest.json` contains a non-empty signature, manually install the DMG,
      and verify the installed app reports Developer ID identity plus stable
      TCC permission state.
- [x] Fix signed-mode certificate import for macOS CI: regenerate the PKCS#12
      as Apple-compatible after `security import` rejected the OpenSSL-default
      bundle, verify import locally with a temporary keychain, and refresh
      `APPLE_CERTIFICATE`/`APPLE_CERTIFICATE_PASSWORD` secrets.
- [x] Add CI keychain chain-prep for signed builds: install Apple's official
      Developer ID G2 intermediate into the self-hosted runner login keychain
      before Tauri invokes `codesign`.
- [x] Replace `APPLE_PASSWORD` with an Apple app-specific password for
      notarization (secret rotated 2026-06-06).
- [x] Diagnose the notarization stall as Apple notary-service backlog (not cert
      or app-size) via `notarytool history` on the validated keychain profile: a
      minimal signed probe app sat `In Progress` alongside both Luna submissions
      for 45–60+ min (log entry 82).
- [x] Rebuild the Luna workflow to an explicit, queue-decoupled notarization
      pipeline: Tauri signs only; explicit `notarytool submit --no-wait` +
      bounded poll + `notarytool log` on failure; staple on Accept; rebuild the
      DMG from the stapled app; publication gated on `notarized == 'accepted'` and
      `main`/`luna-v*` (log entry 83).
- [ ] Finalize once Apple's queue drains: re-run the signed build, confirm
      `notarized == 'accepted'`, then install the rebuilt DMG and verify
      `codesign -dv`, `stapler validate`, `spctl`, and the Computer Use smoke;
      confirm the first stable `luna-latest` updater manifest publishes.
- [ ] (Optional hardening) Create an App Store Connect API key and add
      `APPLE_API_KEY`/`APPLE_API_KEY_ID`/`APPLE_API_ISSUER` secrets to remove the
      brief `store-credentials` password exposure entirely (the workflow already
      prefers the API key when present).
- [x] Luna lead review for the release-signing/permission-onboarding slice:
      Alpha Chat ACKed no blocker before PR/CI signed-build gate and preserved
      the manual first-DMG install requirement after updater-key rotation.
- [x] Codex local review for the release-signing/permission-onboarding slice:
      no blocker found in permission counts, identity metadata display,
      setup-command allow-listing, or Assist/Control actuation gating.
- [ ] Claude Code review for the release-signing/permission-onboarding slice:
      attempted with Opus/max and Sonnet read-only prompts, but the CLI hung on
      substantive review inputs and returned no review result.

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
- [x] Verify `luna-v0.1.98` unsigned development release locally after PR
      #806: DMG checksum, `/Applications/Luna.app` version `0.1.98`, expanded
      chat/session startup, durable `Stopped` posture, disabled native-control
      affordances, visible `Resume`, Luna Alpha Chat lead response, and an empty
      exact Docker `_work` mount gate.
- [x] Verify `luna-v0.1.99` unsigned development release locally after PR
      #807: DMG checksum, `/Applications/Luna.app` version `0.1.99`, installed
      app launched from `/Applications`, expanded chat/session UI, durable
      `Stopped` posture, disabled native-control affordances, Luna Alpha Chat
      lead response through the fixed async Alpha CLI path, and an empty exact
      Docker `_work` mount gate. The Tauri build workflow produced the release
      assets but marked the run failed because GitHub release creation timed out
      before the delayed server-side release became visible; the workflow now
      retries create/upload idempotently.
- [x] Verify `luna-v0.1.100` unsigned development release locally after PR
      #808: DMG checksum, `/Applications/Luna.app` version `0.1.100`, installed
      app launched from `/Applications`, expanded chat/session UI, durable
      `Stopped` posture, disabled native-control affordances, visible Luna
      Alpha Chat handoff, expected ad-hoc unsigned development signature, and
      an empty exact Docker `_work` mount gate.
- [x] Verify `luna-v0.1.101` unsigned development release locally after PR
      #810: DMG checksum, `/Applications/Luna.app` version `0.1.101`, installed
      app launched from `/Applications`, expanded chat/session UI, `Stopped
      Alpha OK Mac Stopped` safety strip, disabled native-control affordances,
      visible `Resume`, expected ad-hoc unsigned development signature, and an
      empty exact Docker `_work` mount gate.
- [x] Verify Docker Desktop deployment no longer bind-mounts the GitHub Actions
      `_work` checkout for source-mounted runtime services. Precise inspection
      found zero `/actions-runner/_work` paths, and Luna's broader `grep _work`
      smoke returns empty after live stack migration.
- [x] Make Luna release creation/upload idempotent with retries so a delayed
      GitHub release API side effect does not leave a valid artifact publication
      red on the release gate.
- [x] Harden Alpha Chat CLI against transient Cloudflare/SSE stream-open
      failures by polling the durable job, reconnecting by sequence while it is
      running, and hydrating the persisted result message when the job already
      completed.

Exit criteria:

- [ ] Installed signed Luna can fetch a valid updater manifest once signing is
      re-enabled.
- [ ] Signed `latest.json` points at `nomad3/agentprovision-agents` and
      includes a non-empty signature.
- [ ] First signed/notarized Luna release with the rotated updater public key
      is manually installed from DMG; automatic updater validation starts from
      that installed build forward.
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
- [x] Local install smoke from GitHub Release `luna-v0.1.98` confirms version,
      checksum, expanded chat/session launch, durable stopped posture,
      disabled native-control controls, Luna Alpha Chat lead response, and an
      empty exact Docker `_work` mount gate.
- [x] Local install smoke from GitHub Release `luna-v0.1.99` confirms version,
      checksum, installed `/Applications/Luna.app` launch, expanded chat/session
      window, durable stopped posture, disabled native-control controls, Luna
      Alpha Chat lead response, and an empty exact Docker `_work` mount gate.
- [x] Local install smoke from GitHub Release `luna-v0.1.100` confirms version,
      checksum, installed `/Applications/Luna.app` launch, expanded chat/session
      window, durable stopped posture, disabled native-control controls, Luna
      Alpha Chat handoff visibility, expected ad-hoc signature, and an empty
      exact Docker `_work` mount gate.
- [x] Local install smoke from GitHub Release `luna-v0.1.101` confirms version,
      checksum, installed `/Applications/Luna.app` launch, expanded chat/session
      window, `Stopped Alpha OK Mac Stopped`, disabled native-control controls,
      expected ad-hoc signature, and an empty exact Docker `_work` mount gate.

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
  - [x] Enforce passive local permission readiness before Screen Recording and
        Accessibility-backed observations. System Events automation remains a
        visible readiness signal, but the passive `unknown` probe no longer
        blocks Accessibility-gated active-app metadata; runtime lookup failures
        still audit and deny.
  - [x] Emit local metadata-only `desktop-control-audit` events for observation
        start, success, failure, and denial.
  - [x] Gate background clipboard/activity emitters with the same local
        observation policy before emitting frontend events, and emit matching
        local audit events for emitted observations.
  - [x] Re-scope macOS active-app observation to Accessibility readiness so
        passive System Events `unknown` does not permanently block monitoring.
        Keep runtime System Events failures fail-closed with audit.
  - [x] Route ambient macOS activity events through metadata-only app-switch
        payloads: app names, duration, timestamp, source, and title presence/
        character count only; no raw window titles, subprocess args, terminal
        cwd, or project labels are emitted.
  - [x] Make direct `get_active_app` command results metadata-only as well:
        app name, title presence, and title character count; no raw window title
        is returned to the WebView or command-completion metadata.
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
- [x] Surface Alpha CLI local-kernel discovery and macOS app-monitor readiness
      in the Luna Tauri safety state/UI without advertising new API
      capabilities.
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
        preflight, Accessibility uses `AXIsProcessTrusted`, System
        Events/Automation uses `AEDeterminePermissionToAutomateTarget` with
        `askUserIfNeeded=false`, and Camera/Mic use
        `AVCaptureDevice.authorizationStatusForMediaType`. Luna must not
        trigger TCC prompts by merely opening the chat window.
- [x] Add user-facing permission setup actions in the TCC panel for denied or
      unknown macOS permissions. The buttons open scoped Privacy & Security
      panes through Tauri command `control_open_permission_setup`; they do not
      grant permissions automatically and do not enable native actuation.
- [x] Add running-app TCC identity diagnostics to the permission modal so
      unsigned/ad-hoc release and debug builds that share the Luna display name
      but have different macOS code identities are visible to the user.
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
- [x] Add API service for enqueue, claim, complete, deny, expire.
  - [x] Add API service for local metadata-only observation-event ingestion.
  - [x] Add first command queue service for observation-only commands:
        enqueue, device-bound claim lease, complete, deny, stale expiry,
        duplicate terminal idempotency, and Stop preemption.
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
- [x] Add authenticated Tauri polling/SSE hook for claimable-command notices.
  - [x] Add Luna client polling hook that claims commands with the enrolled
        desktop device token and active chat session id.
- [x] Require Tauri claim before execution; down-channel notices alone never
      execute commands.
- [ ] Add signed action envelope validation in Tauri.
  - [x] Add first API-side signed command envelope issuance and server-side
        verification on completion for claimed desktop commands. This uses an
        HMAC envelope over tenant/user/session/command/shell/device/action/
        capability/policy/expiry/nonce fields and keeps Tauri native actuation
        denied by default.
  - [x] Add Luna client claimed-envelope preflight before any native invoke:
        claimed commands with missing nonce, missing/invalid signature metadata,
        unsupported schema/policy/issuer, stale expiry, or mismatched command/
        session/shell/device/action/capability binding complete as denied before
        Luna calls local observation commands or native-control stubs. This is
        contract validation only; native-control cryptographic verification is
        handled by the follow-up Ed25519 proof slice.
  - [x] Add opt-in API Ed25519 command-envelope issuance and Tauri-side
        Ed25519 verification for native-control proof requests. HMAC remains
        the default/API completion-compatible envelope for observe commands, but
        native pointer/keyboard proof requests now require Ed25519, the expected
        key id, a configured Luna public key, canonical signature verification,
        nonce/binding checks, and still terminate with `tier_enabled=false`
        before any macOS actuation.
- [ ] Add server-time TTL, nonce storage, monotonic per-device sequence numbers,
      and replay-window cleanup.
  - [x] Add server-time lease expiry and pending-command TTL for the
        observation-only queue. Signed envelope expiry, per-device sequence
        numbers, replay cleanup, and grant-bound TTL remain pending.
  - [x] Add durable `desktop_command_envelope_nonces` storage for issued
        envelope nonces. Completion requires the matching envelope nonce,
        consumes it once, and terminalizes missing, tampered, expired, or
        replayed envelopes with display-safe denial audit events.
- [x] Add one active claim lease per command, compare-and-swap status
      transitions, retry limits, and duplicate completion handling.
  - [x] Implement one active claim lease with CAS status transitions and
        duplicate terminal completion idempotency. Retry limits remain pending.
- [x] Add atomic approval consumption/decrement during command claim or
      execution.
  - [x] Branch `codex/luna-alpha-kernel-adapter` adds explicit
        `desktop_command_approval_grants` rows, an internal grant-creation
        endpoint, approval identity/risk binding in command payloads and signed
        envelopes, and fail-closed claim denial when a command has no usable
        grant.
- [x] Implement approval consumption as a database compare-and-swap update inside
      the command claim transaction.
  - [x] Claim updates require tenant/user/session/shell/device/capability/
        risk/status/expiry/remaining-action predicates and decrement
        `remaining_actions` before a lease/envelope is issued. Missing,
        expired, exhausted, replayed, revoked, or binding-mismatched grants emit
        display-safe denial audit and never reach native invocation.
- [ ] Add command correlation IDs across API, Tauri, MCP, audit, and
      `session_events`.
- [ ] Add config/env/Helm updates in the same PR as any signing, enrollment, or
      device-token secret.
- [ ] Emit `desktop_action_requested`, `started`, `completed`, `denied`, and
      `stopped`.
  - [x] Emit command queued, claimed, completed, preempted, and expired events
        for the observation-only down-channel. Final event names for full
        action envelopes remain pending.
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
  - [x] Add command lifecycle tests for device-bound claim, completion
        idempotency, Stop preemption, stale lease expiry, metadata sanitization,
        stale pending-command expiry, tenant-scoped nonce idempotency, and route
        header plumbing.

Exit criteria:

- [x] A no-op test action can be queued by API, claimed by Tauri, and completed
      into `desktop_command_events` and mirrored into `session_events`.
- [x] Commands for another tenant/user/session/shell are rejected.
- [x] Expired commands are not executed.
- [x] Revoked desktop devices cannot claim commands even if shell presence is
      fresh.
  - [x] Branch `codex/luna-control-policy-tests` adds the command-claim
        regression: a `revoked` desktop `DeviceRegistry` row returns 403 even
        with a valid device token and fresh shell presence, leaving the command
        pending and unleased.
- [x] Stop rejects queued and claimed no-op commands before pointer control
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
- [x] Command enqueue requires authenticated user and valid session.
- [x] Command claim requires matching tenant and shell/device.
- [x] Cross-tenant command claim returns 404 or denial without leaking existence.
- [x] Expired commands cannot be claimed.
- [x] Revoked desktop device cannot claim commands.
  - [x] `test_revoked_desktop_device_cannot_claim_even_with_fresh_presence`
        covers the claim-time registry status gate.
- [x] Duplicate command completion is idempotent and does not create multiple
      success events.
- [x] Command state machine rejects invalid transitions and cannot double-actuate
      one command.
- [x] Stop changes queued or claimed commands to `preempted`, not `succeeded`.
- [x] Completion writes `desktop_command_events` and a display-safe
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
- [x] Raw screenshot and clipboard values are not written to logs or
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
- [x] Phase 2 command down-channel focused local validation passed on branch
      `codex/luna-command-downchannel-gate`:
      `pytest tests/api/v1/test_desktop_command_lifecycle.py
      tests/api/v1/test_desktop_control_events.py
      tests/api/v1/test_desktop_device_binding.py -q` (`46 passed`);
      `ruff check app/api/v1/desktop_control.py
      app/services/desktop_control_service.py app/models/desktop_command.py
      tests/api/v1/test_desktop_command_lifecycle.py
      tests/api/v1/test_desktop_control_events.py
      tests/api/v1/test_desktop_device_binding.py`; `python -m py_compile`
      for touched API/router/model modules.
- [x] Native-control scaffold API validation passed on branch
      `codex/luna-native-control-scaffold`: native pointer/keyboard command
      enqueue records immediate denied audit rows, remains non-claimable, and
      sanitizes raw payload data. `python -m py_compile` passed for touched
      API/router/test modules; targeted `ruff check` passed; and
      `pytest tests/api/v1/test_desktop_command_lifecycle.py
      tests/api/v1/test_desktop_control_events.py -q` passed (`44 passed`).
- [x] PR #803 native-control scaffold PR and post-merge CI passed:
      PR run `27059502069` passed API unit, API integration, Luna client, and
      aggregate checks; main runs `27059620727`, `27059620729`, and
      `27059620724` passed Tests, Docker Desktop Deployment, and Luna Client
      Tauri Build on merge commit `40403fcf`.
- [x] PR #806 native-control safety hardening PR and post-merge CI passed:
      PR run `27064457928` passed API unit, API integration, Luna client, and
      aggregate checks; main Tests run `27064562464`, Docker Desktop Deployment
      run `27064562462`, and Luna Client Tauri Build run `27064562475` passed
      on merge commit `37c6f18a`.
- [x] Signed-envelope gate focused validation passed on branch
      `codex/luna-signed-envelope-gate`: `pytest
      tests/api/v1/test_desktop_command_lifecycle.py
      tests/api/v1/test_desktop_device_binding.py
      tests/api/v1/test_desktop_control_events.py -q` (`58 passed`);
      `ruff check app/services/desktop_control_service.py
      app/models/desktop_command_envelope_nonce.py
      tests/api/v1/test_desktop_command_lifecycle.py`; `python -m py_compile`
      for touched API modules/tests; and `npm test -- --run
      src/hooks/__tests__/useDesktopCommandClaims.test.jsx` (`15 passed`).

### Tauri / Rust

- [x] `cargo check` in `apps/luna-client/src-tauri` passed for
      `codex/luna-command-downchannel-gate`; only existing Rust warnings and
      the local Cargo cache cleanup permission warning were observed.
- [x] Unit tests for local permission decisions.
- [x] Actuator denies when Observe/Assist/Control tier is disabled.
  - [x] Native-control scaffold policy tests prove pointer/keyboard control
        remains disabled and Stop preempts native control before any actuation
        path. Tauri command stubs are registered but return denial-only.
  - [x] Branch `codex/luna-control-policy-tests` adds
        `NativeControlCommandPolicy` coverage for Stop, claim lease, envelope,
        tier, and final deny-by-default behavior.
- [ ] Actuator denies expired and replayed envelopes.
  - [x] API-side expired-envelope and replay/nonce denial is covered by
        completion-time envelope verification. Tauri-side public-key envelope
        replay checks remain pending.
- [x] Actuator denies unsigned envelopes and unsupported policy versions.
- [x] Actuator denies when device claim token is revoked or missing.
  - [x] Missing/invalid token was already covered; branch
        `codex/luna-control-policy-tests` adds revoked/disabled token-device
        status rejection before command claim.
- [x] Actuator requires command claim lease before execution.
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
- [x] Phase 2 Luna client command-claim validation passed:
      `npm test -- --run` in `apps/luna-client` (`136 passed`) and
      `npm run build` succeeded. The new tests cover device-token claim
      polling, local Stop preemption, Observe-mode gating, and metadata-only
      completion summaries.
- [x] Phase 2 claimed-command timeout regression validation passed on branch
      `codex/luna-command-completion-smoke-fix`:
      `npm test -- --run src/hooks/__tests__/useDesktopCommandClaims.test.jsx`
      (`11 passed`). The added tests cover hung post-claim safety checks,
      hung native observation invokes, locked hook-level denial, cancellation
      after claim, and completion retry before backend lease expiry.
- [x] Full Luna client validation for
      `codex/luna-command-completion-smoke-fix` passed:
      `npm test -- --run` (`142 passed`) and `npm run build` succeeded with
      only the existing Vite dynamic/static import and chunk-size warnings.
- [x] API timezone regression validation for `codex/luna-v0196-validation`
      passed:
      `pytest tests/api/v1/test_desktop_command_lifecycle.py -q`
      (`15 passed`);
      `pytest tests/api/v1/test_desktop_command_lifecycle.py
      tests/api/v1/test_desktop_control_events.py
      tests/api/v1/test_desktop_device_binding.py -q` (`47 passed`);
      targeted `ruff check` and `python -m py_compile` for the touched API
      service/test modules.
- [x] Native-control scaffold Luna client validation passed:
      `npm test -- --run src/hooks/__tests__/useDesktopCommandClaims.test.jsx`
      (`14 passed`), full `npm test -- --run` (`145 passed`),
      `npm run build`, focused Rust policy/control tests, and full
      `cargo test` in `apps/luna-client/src-tauri` (`69 passed`). Existing
      Cargo cache cleanup permission warning and pre-existing Rust warnings
      were observed.
- [x] macOS Alpha-kernel/readiness slice focused validation passed on branch
      `codex/luna-macos-alpha-kernel`: `cargo test
      computer_use::policy::tests --quiet` (`12 passed`), targeted Rust privacy
      helper tests for active-app metadata and activity-event metadata, `cargo
      check`, `npm test -- --run ControlSafetyStrip.test.jsx
      CommandPalette.test.jsx useDesktopCommandClaims.test.jsx` (`36 passed`),
      `pytest tests/api/v1/test_desktop_command_lifecycle.py::test_completion_sanitizes_reason_and_metadata_values
      -q` (`1 passed`), and `git diff --check`. The local Cargo cache cleanup
      permission warning and existing gesture/spatial warnings remain
      non-blocking.
- [x] Claimed-envelope preflight focused Luna client validation passed on branch
      `codex/luna-v0101-approval-trust`: `npm test -- --run
      src/hooks/__tests__/useDesktopCommandClaims.test.jsx` (`25 passed`).
      Added coverage proves valid claim envelopes are the normal path and that
      missing, nonce-less, unsigned, expired, command/session/shell/device/
      action/capability-mismatched envelopes complete as denied before native
      invocation.
- [x] Claimed-envelope preflight broader Luna client validation passed:
      `npm test -- --run` (`158 passed`), `npm run build`, and
      `git diff --check`. The build kept the existing Vite dynamic/static
      import and chunk-size warnings.
  - [x] macOS app-monitor event-contract validation passed on branch
      `codex/luna-v0102-validation-next`: focused `npm test -- --run
      src/utils/__tests__/macosAppMonitor.test.js
      src/hooks/__tests__/useActivityTracker.test.jsx
      src/components/__tests__/ControlSafetyStrip.test.jsx` (`21 passed`);
      Rust metadata tests
      `metadata_app_switch_event_omits_raw_window_and_subprocess_context` and
      `active_app_metadata_omits_raw_window_title`; full `npm test -- --run`
      (`164 passed`); `npm run build`; full `cargo test --quiet` (`76 passed`);
      API `pytest tests/api/v1/test_activities.py -q` (`3 passed`);
      targeted `ruff check` and `python -m py_compile` for the activity API;
      and `git diff --check`. Existing Vite chunk/import warnings and the
      local Cargo cache cleanup permission warning remain non-blocking.
  - [x] Approval trust-boundary focused validation passed on branch
        `codex/luna-alpha-kernel-adapter`: `pytest
        tests/api/v1/test_desktop_command_lifecycle.py
        tests/api/v1/test_desktop_control_events.py
        tests/api/v1/test_desktop_device_binding.py -q` (`65 passed`),
        `npm test -- --run src/hooks/__tests__/useDesktopCommandClaims.test.jsx`
        (`28 passed`), full `npm test -- --run` in `apps/luna-client`
        (`167 passed`), `npm run build`, targeted `ruff check`, `python -m
        py_compile` for touched API route/service/model/test files, and
        `git diff --check`.

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
- [x] `luna-v0.1.95` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.95`, ad-hoc unsigned development signature confirmed,
      chat-first expanded startup verified with Computer Use, API/tunnel stack
      healthy, and Luna's exact Docker `_work` mount gate returned no output.
- [x] `luna-v0.1.95` command down-channel smoke follow-up: installed app
      claimed an internal `get_active_app` command, but did not post terminal
      completion; backend expired the lease. Closed by PR #800 client
      hardening plus PR #801 API lease-time fix, validated with the installed
      `luna-v0.1.96` command smoke.
- [x] `luna-v0.1.96` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.96`, ad-hoc unsigned development signature confirmed,
      chat-first expanded startup verified with Computer Use, durable
      `Stopped` relaunch verified, and Luna lead review response visible.
- [x] `luna-v0.1.96` command down-channel smoke: installed app claimed
      `get_active_app` and attempted `/complete`, but API completion raised a
      mixed-timezone lease comparison error and the command expired before PR
      #801. After PR #801 deployed, the same installed app was restarted to
      re-register shell presence; command
      `0dd3bb2a-d119-4e77-8580-96a356c7b529` was queued, claimed, and completed
      before lease expiry with status `denied`, `/complete` HTTP 200, no raw
      marker persistence, and no `TypeError`/500 recurrence.
- [x] `luna-v0.1.97` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.97`, ad-hoc unsigned development signature confirmed,
      `spctl` rejection accepted as expected for unsigned development,
      chat-first expanded startup verified with Computer Use, public/local API
      bases healthy, and Luna's exact Docker `_work` mount gate returned no
      output.
- [x] `luna-v0.1.97` native scaffold command smoke: internal `pointer_click`
      returned immediate terminal `denied`, remained non-claimable, persisted
      no raw marker text, and mirrored only display-safe session payload.
      Active-session `get_active_app` was claimed by the installed app and
      completed `denied` before lease expiry with marker text absent from
      command payload and event metadata; final queue check returned zero
      pending commands for the live shell.
- [x] `luna-v0.1.98` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.98`, ad-hoc unsigned development signature confirmed,
      chat/session expanded startup verified with Computer Use, durable
      `Stopped` posture verified, Observe/Assist/Control/Lock/Stop disabled,
      `Resume` visible, Luna's Alpha Chat lead response visible, and Luna's
      exact Docker `_work` mount gate returned no output.
- [x] `luna-v0.1.99` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.99`, ad-hoc unsigned development signature confirmed,
      installed Tauri app verified with Computer Use, expanded chat/session UI
      visible, durable `Stopped` posture verified, Observe/Assist/Control/Lock/
      Stop disabled, `Resume` visible, Luna's Alpha Chat lead response visible,
      and Luna's exact Docker `_work` mount gate returned no output.
- [x] `luna-v0.1.100` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.100`, ad-hoc unsigned development signature confirmed,
      installed Tauri app verified with Computer Use, expanded chat/session UI
      visible, durable `Stopped` posture verified, Observe/Assist/Control/Lock/
      Stop disabled, `Resume` visible, Luna's Alpha Chat handoff visible, and
      Luna's exact Docker `_work` mount gate returned no output.
- [x] `luna-v0.1.101` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.101`, ad-hoc unsigned development signature confirmed,
      installed Tauri app verified with Computer Use, expanded chat/session UI
      visible, `Stopped Alpha OK Mac Stopped` safety strip verified, Observe/
      Assist/Control/Lock/Stop disabled, `Resume` visible, no native actuation,
      and Luna's exact Docker `_work` mount gate returned no output.
- [x] `luna-v0.1.102` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.102`, ad-hoc unsigned development signature confirmed,
      no `TeamIdentifier`, installed Tauri app verified with Computer Use,
      expanded chat/session UI visible, `Stopped Alpha OK Mac Stopped` safety
      strip verified, Observe/Assist/Control/Lock/Stop disabled, `Resume`
      visible, window geometry measured `0,34 1496x933`, Luna ACKed the gate in
      Alpha Chat, and Luna's exact Docker `_work` mount gate returned no
      output.
- [x] `luna-v0.1.103` release/install smoke: DMG checksum verified, installed
      bundle version `0.1.103`, ad-hoc unsigned development signature confirmed,
      no `TeamIdentifier`, installed Tauri app verified with Computer Use,
      expanded chat/session UI visible at `0,38 1728x1079`, `Stopped Alpha OK
      Mac Stopped` safety strip verified, Observe/Assist/Control/Lock/Stop
      disabled, `Resume` visible, no native actuation, Luna ACKed the gate in
      Alpha Chat, and Luna's exact Docker `_work` mount gate returned no
      output.
- [x] `luna-v0.1.103` pre-PR Computer Use build smoke on
      `codex/luna-alpha-kernel-adapter`: installed bundle version `0.1.103`
      remained responsive; `Resume -> Control Locked`, `Observe -> Mac Denied`,
      and `Stop -> Stopped` transitions worked; Assist and Control stayed
      disabled throughout; pointer/keyboard actuation remained unavailable.
- [x] `luna-v0.1.104` release/install smoke after PR #813: main Tests, Docker
      Desktop Deployment, and Luna Client Tauri Build passed; DMG checksum
      verified directly with `shasum -c`; installed bundle version `0.1.104`;
      ad-hoc unsigned development signature confirmed with no `TeamIdentifier`;
      Docker `_work` mount gate returned no output; Computer Use verified
      authenticated chat/session startup, `Stopped -> Control Locked ->
      Observe Mac Denied -> Stopped` transitions, Assist/Control disabled, and
      no pointer/keyboard actuation.
- [x] Current branch permission-onboarding smoke: open `TCC` details in Luna,
      verify the modal shows the running app identity, denied Screen/AX rows
      show `Enable`, unknown rows show `Open`, granted/not-required rows stay
      read-only, and clicking each setup action opens only the matching macOS
      Privacy & Security pane. Computer Use verified the branch debug bundle
      shows `Stopped Alpha OK Mac Stopped`, the high-contrast TCC popup, running
      app identity `ad-hoc | luna-c475546d746c42c2`, explicit non-Applications
      TCC-scope note, Screen/AX `Enable`, Camera/Mic `Open`, no Assist/Control
      enablement, and correct routing to Screen & System Audio Recording,
      Accessibility, Camera, and Microphone settings panes.
- [x] PR #816 signed smoke artifact install: run `27077213653` uploaded
      artifact `7459146318`; checksum verified; installed `/Applications/Luna.app`
      version `0.1.105` with Developer ID team `KF9LPYY7KK` and CDHash
      `d7af69145fc45eb6c17a76480f220a26c1b7b0a8`; Computer Use verified
      authenticated expanded startup, TCC `4/4`, `Stopped -> Control Locked ->
      Observe -> Stopped`, Assist/Control disabled, and no pointer/keyboard
      actuation; Docker `_work` mount gate returned no output.
- [x] PR #816 Luna lead review after signed smoke install: Luna Supervisor
      verified remote head `e2e652d5` and accepted the branch as PR-ready/
      review-ready for the native-boundary proof slice, with no code-level
      native-actuation blocker and the notarized-release gate still open.
- [x] PR #816 body updated with native-boundary proof scope, signed smoke
      validation, explicit non-cryptographic verifier caveat, and pending
      notarized-release gate; PR marked ready for review.
- [ ] PR #816 signed/notarized release gate: rerun Tauri build when Apple
      notary returns Accepted, then verify stapled DMG/app with `stapler` and
      `spctl`, install the notarized DMG locally, and validate updater/release
      publication from the accepted path.
- [x] PR #816 review gate update: Luna Code Reviewer returned no code-level
      native-control blocker and recommended holding only for signed/notarized
      CI plus first-DMG install/updater validation. Luna Supervisor Alpha Chat
      hit the known Cloudflare 524 path. Claude hosted `ultrareview` was
      unavailable because usage credits were exhausted; local Claude Code
      Opus/max fallback stayed silent for over 13 minutes and was terminated
      before it consumed more resources. Codex review found a release-workflow
      blocker for signed manual branch builds: `luna-latest` publication was
      gated only on signed mode, while release creation is skipped off `main`/
      `luna-v*` tags. The in-flight branch run `27071553333` was cancelled
      before release-publication steps, and the workflow guard was tightened so
      stable updater manifest publication only runs on `main` or `luna-v*` tags.
- [x] Developer ID integrity check after the long signed branch build:
      Certificate Assistant had been stuck during the macOS UI flow, but the
      certificate material itself validated locally. The Developer ID
      Application certificate parses cleanly as `Developer ID Application:
      Simon Aguilera (KF9LPYY7KK)`, issued by Apple Developer ID G2, valid
      `2026-06-06` through `2031-06-07`, with fingerprint
      `A0:BF:89:39:3D:7C:AC:07:8B:0A:42:35:19:F2:50:2F:62:9C:88:28:04:29:6E:BC:0E:CD:DB:F9:22:1B:ED:F4`.
      The certificate modulus matches the private key, the Apple-compatible P12
      contains a certificate bag plus shrouded keybag, and the P12 certificate
      matches the private key. The signed branch run was not compiling; it was
      sleeping inside Apple's `notarytool submit --wait` for the uploaded Luna
      ZIP. Root cause to pursue if the run times out: notarization wait
      reliability and secret handling, not corrupted cert material.
- [x] Signed branch run `27071762194` timed out after `30m21s`. Logs show
      release compile finished in about one minute, Developer ID certificate
      import succeeded, Luna binaries and app bundle were signed with
      `Developer ID Application: Simon Aguilera`, and Tauri entered
      notarization at `2026-06-06T19:32:18Z`. GitHub cancelled the job at
      `2026-06-06T20:01:01Z`, after about `28m43s` inside Apple's
      notarization wait. Tauri's own installed bundler docs note first
      notarization can take multiple hours, so the workflow timeout was raised
      from 30 to 120 minutes. Follow-up remains: move notarization auth to
      App Store Connect API key or a keychain profile path so the app-specific
      password is not visible in local process arguments on the self-hosted
      runner.
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

1. Keep the PR #816 merge recorded as a proof-slice landing only: Luna accepted
   main at `e072f8bf`, but the accepted/stapled release path is still open.
2. Re-run the Luna Tauri Build once Apple's notary queue accepts the app, or
   after App Store Connect API-key secrets are added, and do not mark the signed
   release gate complete until the accepted path verifies stapled app+DMG,
   `spctl`, local install, updater manifest, and release publication.
3. Exercise the proof command in an installed local branch build once a native
   command claim can be queued safely, and verify `desktop_native_control_denied`
   audit metadata reaches the expected Luna/session surfaces.
4. Extend the Alpha-kernel adapter beyond readiness:
   auth/session handoff, chat-job streaming from `alpha`, cancellation, error
   display, offline behavior, release packaging, and app-monitor event mapping
   into Luna UI.
5. Add an API/Alpha CLI parity checklist for every Luna-facing platform
   capability: if API endpoints, schemas, or event types change, add matching
   Alpha CLI/core support and tests in the same PR.
6. Finish the Ed25519 production key lifecycle before canary actuation:
   generate/store the API signing key, distribute the pinned Luna public key in
   release/installer config, rotate/revoke keys, and mirror Helm/GitHub secrets
   so local proof verification and deployed envelopes use the same trust root.
7. Re-review approval grant creation/consumption with council and Luna after the
   local verifier lands, then decide whether a narrow canary pointer execution
   gate can be designed without broad macOS actuation.
8. Keep real pointer, keyboard, clipboard-write, and global macOS actuation
   disabled until signed envelopes, replay defense, approval grant consumption,
   device trust checks, and privacy/TCC boundaries are implemented and reviewed.
9. Close remaining pre-live-content hardening gaps: disable or display-safe route
   ambient clipboard/activity raw emissions, and add remaining revoked/offline
   regression coverage around Stop and shell reconnect behavior.
10. Treat the post-deploy `No connected desktop shell` observation as a
   hardening follow-up: Luna should re-register shell presence after API
   restarts or heartbeat failures, not require an app restart.
11. Include the PR #797 command-palette maximize follow-up in the next branch or
   explicitly keep it as a separate UX hardening item.
