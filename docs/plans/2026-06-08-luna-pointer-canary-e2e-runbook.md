# Luna pointer canary — production E2E runbook

Date: 2026-06-08
Status: ready to run (all code merged: #837/#838 Phase 2.75, #839 client
actuation, #840 server issuance, #841 client prove→actuate wiring)

This is the live end-to-end test of the Phase 3 pointer canary on the installed
Luna app: API issues a signed pointer command → Luna claims → proves the
boundary → actuates the **real cursor** → reports the result. It moves the
actual mouse on this machine, so it is run deliberately, against a safe target,
with Stop ready.

## Preconditions

- All four PRs merged to main, and a fresh Luna build (post-#841 DMG) **installed**
  in `/Applications/Luna.app`. The currently-installed build predates the Phase 3
  code. Notarization is on Apple hold → install the **unstapled** CI artifact
  (`gh run download` the luna-client-build run, or right-click→Open / clear the
  quarantine xattr to launch).
- The docker-compose stack is running (it is).
- A second computer-use agent (Codex) is currently active on this machine — pause
  it during the cursor test so two agents don't fight for the pointer.

## 1. Configure the API for native control (ed25519 + allowlist)

The running api uses HMAC + an empty allowlist. Native control requires Ed25519
and an allowlisted target bundle. Generate a keypair and set, on the `api`
service env (compose/helm — replicate to both; restart api with the #765 drain so
no WhatsApp QR re-pair):

```
DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM=Ed25519
DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY=<b64url 32-byte seed>
DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID=agentprovision-desktop-command-ed25519-v1
DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST=<safe target bundle id, e.g. com.apple.TextEdit>
```

Keypair (run locally, keep the private key out of git/logs):
```
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; k=Ed25519PrivateKey.generate(); pk=k.private_bytes_raw(); pub=k.public_key().public_bytes_raw(); print('PRIV', base64.urlsafe_b64encode(pk).decode().rstrip('=')); print('PUB', base64.urlsafe_b64encode(pub).decode().rstrip('='))"
```

## 2. Configure the Luna client

Launch the new Luna with:
```
LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY=<PUB from step 1>
LUNA_ACTUATION_POINTER_ENABLED=true
```
Grant **Accessibility** to the new Luna.app (System Settings → Privacy &
Security → Accessibility) — the enigo cursor move needs it. Keep the **Stop**
control visible.

## 3. Issue a pointer command (server side)

With the API internal key, create a native_control approval grant for the
allowlisted target, then enqueue a `pointer_move` command bound to it:

- `POST /api/v1/desktop-control/internal/approval-grants` — risk_tier=native_control,
  capability=pointer_control, target_binding={bundle_id:<allowlisted>, action:pointer_move},
  expires_in_seconds≈60, session_id=<the Luna session>.
- `POST /api/v1/desktop-control/internal/commands` — action=pointer_move,
  tool_name=desktop_pointer_move, approval_id=<grant>, payload.target={same binding}.

Headers: `X-Internal-Key`, `X-Tenant-Id` (+ user resolution per the internal deps).

## 4. Observe

- Bring the allowlisted target app frontmost.
- Luna polls, claims the command (receives the Ed25519 envelope), proves the
  boundary (8 gates), and actuates: the **cursor moves to the centre of the
  active display**. The command completes `succeeded`; a `desktop-native-actuation`
  event fires (`outcome=actuated`).
- **Stop test**: enqueue another command, then hit Stop before/while it actuates →
  the boundary/actuation re-check denies (`stopped`) and the command reports
  `preempted` — no cursor move.
- **Flag-off test**: relaunch Luna without `LUNA_ACTUATION_POINTER_ENABLED` →
  the same command is denied `native_control_tier_disabled`; no cursor move.

## Exit criteria (Phase 3 plan)

1. Canary works only against the allowlisted frontmost target. ✓ via allowlist +
   frontmost re-check.
2. Stop preempts before movement and between movement/click. ✓ via mode re-check
   + lease release on Stop.
3. Denied/stopped cases as well covered as success. ✓ (unit + the Stop/flag-off
   live checks above).

## Safety notes

- The canary moves to display centre only — no drag, no multi-click, no
  cross-app, no hidden-window interaction.
- Flag default-off; this is the only context it is enabled.
- Turn the pointer flag back OFF after the test.
