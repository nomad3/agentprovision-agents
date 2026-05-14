# Claude integration: API-key path (option a)

**Date:** 2026-05-14
**Branch:** `feat/claude-auth-api-key-path`
**Status:** Implementing — API endpoint only; UI is a follow-up

## TL;DR

Add `POST /api/v1/claude-auth/api-key` that stores an Anthropic Console API key as the tenant's Claude credential. Bypasses the subscription-OAuth flow (`/start`, `/status`) that's architecturally broken inside the api container (claude CLI can't receive its localhost OAuth callback there). Same credential vault slot, different `credential_type`, so downstream consumers branch on type.

## Why this is needed

Diagnosed during the cli-v0.7.4 e2e test:
- `POST /api/v1/claude-auth/start` spawns `claude auth login --claudeai` inside the api container
- claude CLI v2.1.140 prints a URL, waits for either browser callback OR stdin paste-code
- The container has no browser, no exposed callback port, and the agentprovision UI has no input to forward the paste-code to the subprocess's stdin
- Subprocess blocks forever, deploy state machine eventually errors out

Three fixes were on the table. This PR ships **option a** (cheapest): direct API-key path. **Option b** (stdin-forwarding for the OAuth subprocess) is a future PR if you want the subscription-billing flow to keep working.

## Implementation

`apps/api/app/api/v1/claude_auth.py` — new endpoint after `/cancel`:

```python
class ClaudeApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=20, ...)

@router.post("/api-key")
def claude_auth_set_api_key(body, current_user, db):
    # 1. Normalise common paste artefacts
    raw = body.api_key.strip()
    for prefix in ("ANTHROPIC_API_KEY=", "Bearer ", "bearer ", ...):
        raw = raw.removeprefix(prefix)
    # strip surrounding quotes (.env-style)
    if raw.startswith(('"', "'")) and raw.endswith(('"', "'")):
        raw = raw[1:-1]

    # 2. Sanity-check prefix
    if not raw.startswith("sk-ant-"):
        raise HTTPException(400, "...console.anthropic.com/settings/keys")

    # 3. Get-or-create IntegrationConfig + store_credential
    ...
    store_credential(..., credential_type="api_key", credential_key="api_key")
    return {"status": "connected", "connected": True, "credential_type": "api_key"}
```

### Paste-artefact handling

Anthropic key-paste from common places includes wrapper garbage. The endpoint strips:
- `ANTHROPIC_API_KEY=` (`.env` line)
- `ANTHROPIC_API_KEY: ` (YAML line)
- `Bearer ` / `bearer ` (`curl -H "Authorization: ..."` example)
- Surrounding single or double quotes (`KEY="sk-ant-..."`)

Then validates the `sk-ant-` prefix — catches the common mistakes (OpenAI `sk-proj-` keys, Claude.ai session cookies, random text).

### Same vault slot as the OAuth flow

The endpoint:
1. Looks up `IntegrationConfig(integration_name='claude_code')` for the tenant.
2. Creates it if missing OR flips `enabled=True` if disabled — same shape as `_persist_credentials`.
3. Calls `store_credential(...)` with `credential_type='api_key'`.

`store_credential` already revokes any previous active credential for the same `(integration_config_id, credential_key)` pair, so switching between flows works without manual cleanup.

Downstream consumers (orchestration, MCP tools) branch on `credential_type`:
- `'api_key'` → use as `Authorization: Bearer sk-ant-...` against `api.anthropic.com`
- `'oauth_token'` → use the existing claude CLI subprocess path

That branch needs to exist in the consumer code — verify before merging that downstream readers actually handle the new type, otherwise this PR ships a credential nothing uses.

## Tests

7 cases in `apps/api/tests/api/v1/test_claude_auth_api_key.py`:

1. Happy path stores `credential_type='api_key'`
2. Non-Anthropic prefix (OpenAI `sk-proj-...`) → 400 with pointer to `console.anthropic.com`
3. `.env`-line prefix stripped
4. `Bearer ` prefix stripped
5. Double-quote wrapping stripped
6. Short string → 422 (pydantic `min_length=20`)
7. Existing `IntegrationConfig` reused (not duplicated)

## UI follow-up (separate PR)

`apps/web/src/components/IntegrationsPanel.js` — claude_code section currently only shows the "Connect with Anthropic" OAuth button. Add an "Or paste an API key" disclosure that:
- Reveals an `<input type="password">` for the key
- POSTs to `/api/v1/claude-auth/api-key` on Save
- Updates the connected state on success
- Surfaces server `detail` on error

Out of scope for this PR — endpoint can be exercised via curl in the meantime:

```bash
curl -X POST https://agentprovision.com/api/v1/claude-auth/api-key \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-ant-..."}'
```

## What this does NOT do

- Doesn't fix the subscription-OAuth flow (still architecturally broken; option b is the real fix when needed)
- Doesn't add the UI input (next PR)
- Doesn't change how consumers READ the credential — they'll need to branch on type if they want to use API keys

## References

- Session diagnosis of the OAuth subprocess hang
- `apps/api/app/services/orchestration/credential_vault.py` `store_credential`
- `apps/api/app/models/integration_config.py`
