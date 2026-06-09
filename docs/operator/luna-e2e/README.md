# Luna macOS computer-use — real-life E2E suite

Operator harness that drives the **live installed `Luna.app`** through the full
server-issued → Ed25519-signed → boundary-gated → `enigo` actuation path on a real
machine. It is the end-to-end counterpart to the unit tests in
`apps/luna-client/src-tauri` (cargo) and `apps/api/tests` (pytest): those prove the
gate *logic*; this proves the *wires connect* and the OS actually moves the cursor
and accepts synthetic keystrokes.

Ground truth plan: [`docs/plans/2026-06-07-luna-macos-app-control-plan.md`](../../plans/2026-06-07-luna-macos-app-control-plan.md).

## What it covers

| Case | Kind | Asserts |
|---|---|---|
| **P1** `pointer_move` | allow | command reaches `succeeded`; cursor moves to screen centre |
| **P2** `pointer_click` | allow | command reaches `succeeded` |
| **K1** `keyboard_type` | allow | command reaches `succeeded`; client types its fixed canary string (`luna canary`); server never persists the text |
| **K2** `keyboard_key_chord` | allow | command reaches `succeeded`; Right-arrow chord posts |
| **D1** non-allowlisted target | deny | enqueue refused (or command never actuates) — `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` gate |
| **D2** capability mismatch | deny | keyboard command on a pointer grant never actuates — capability gate |
| **D3** budget exhaustion | deny | `max_actions=1` grant actuates once, the second is refused |

Each allow case logs the audit `reason` (`ok` on success) from
`desktop_command_events`. Pointer/keyboard share the same boundary; the suite
proves both capabilities independently.

## Prerequisites

1. **Phase 4 deployed.**
   - API: `apps/api/app/services/desktop_control_service.py` →
     `_DISABLED_NATIVE_CONTROL_ACTIONS == frozenset()` (keyboard issuance enabled, PR #844).
   - Luna DMG: keyboard canary present (`canary_type_text` / `canary_key_chord`, PRs #843/#845).
   - These ship via the normal CI DMG build on merge to `main` — never build Luna locally.
2. **API has the E2E signing config.** A CI auto-deploy recreates the api from the
   runner workdir and wipes the local `.env` extras, so after any deploy:
   ```bash
   docker compose up -d --force-recreate api
   ```
   The relevant `.env` keys: `DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM=Ed25519`,
   `DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY`, `…_KEY_ID`,
   `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` (includes `com.agentprovision.luna`).
3. **Luna launched with the per-capability flags** (the suite's `launch_luna`
   helper does this if Luna isn't already running):
   ```bash
   LUNA_ACTUATION_POINTER_ENABLED=true LUNA_ACTUATION_KEYBOARD_ENABLED=true \
     LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY=<pubkey> \
     /Applications/Luna.app/Contents/MacOS/luna &
   ```
   An **api restart wipes in-memory presence**, so Luna must be (re)launched *after*
   the api is up to re-register its shell (a `PUT /presence` heartbeat alone does
   not re-register capabilities/device).
4. **macOS Accessibility granted** to Luna (`AXIsProcessTrusted()` — this is what
   CGEvent posting needs; Automation/System Events is a *different*, unneeded
   permission). Grant in System Settings → Privacy & Security → Accessibility.
5. A **chat session owned by the test user** exists (the suite picks the latest).

## Run

```bash
bash docs/operator/luna-e2e/computer-use-suite.sh
```

Exit `0` = all cases passed. Override `LUNA_E2E_TENANT_ID` / `LUNA_E2E_USER_ID` /
`LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY` via env for a different tenant.
The internal key is read from `apps/api/.env` at runtime — **no secret is committed**.
`shell_id` is read from `~/Library/Application Support/com.agentprovision.luna/desktop-shell-id`
(persisted by Luna; stable across restarts *and* reinstalls).

## Manual safety cases (not scripted — need a human/UI)

These two gates are covered by Rust unit tests, but to exercise them live you need
UI / a focused field, so they are intentionally out of the automated batch:

- **Durable Stop latch (kill switch).** Click **Stop** in the Control safety strip.
  Re-run the suite → every case is `denied` with `reason=stopped`. The latch at
  `~/Library/Application Support/com.agentprovision.luna/desktop-control-stop`
  persists across restarts and is cleared **only** by the UI **Resume**
  (`control_clear_stop`) — deleting the file is deliberately not enough.
- **Secure-input fail-closed.** Focus a password field (e.g. the macOS login-items
  password sheet) and fire **K1**. The keyboard canary must be `denied` —
  `IsSecureEventInputEnabled()` is re-checked at actuation time, fail-closed.

## Reliability evidence

The pointer path additionally has an overnight soak (`/tmp/luna-e2e/overnight-test.sh`,
27 iterations @ 20 min, self-healing) logged to `/tmp/luna-e2e/overnight-results.log`.
Keep that as the longitudinal pointer signal; this suite is the per-change gate.
