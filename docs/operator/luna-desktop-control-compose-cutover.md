# Luna Desktop-Control Compose Cutover

This checklist is the durable operator gate for the D3 compose change that makes
`apps/api/.env` the source of desktop-control signing values. Do this before the
next compose deploy that includes PR #872.

## Required values

Add or move these untracked, secret-bearing values into `apps/api/.env` on the
deployment host:

```dotenv
DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM=Ed25519
DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY=<base64url-or-hex-ed25519-private-key>
DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID=agentprovision-desktop-command-ed25519-v1
DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST=com.agentprovision.luna,com.apple.TextEdit,net.whatsapp.WhatsApp
```

`DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` is the global native-control floor. If
it is empty, native control denies every bundle even when the signing key is
valid.

## Validation

Before deploy:

```bash
cd apps/api
alpha desktop preflight run
```

Expected result for the operator canary path:

- signing algorithm is `Ed25519`
- Ed25519 key id is `agentprovision-desktop-command-ed25519-v1`
- Ed25519 private key is present and accepted
- canary floor includes `com.agentprovision.luna`

If the key is missing or invalid, the API should still boot, but native desktop
commands must fail closed before any command envelope is issued.

## Boundaries

Only the API signs desktop command envelopes. Orchestration worker, code-worker,
and MCP deployments intentionally use `Ed25519` with an empty private key so they
stay fail-closed if desktop-control signing code is accidentally imported there.
