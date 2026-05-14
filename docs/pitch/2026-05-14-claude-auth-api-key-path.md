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

# Case-insensitive prefix peel, ordered longest-first so
# `export ANTHROPIC_API_KEY=` strips before `ANTHROPIC_API_KEY=`.
_API_KEY_PASTE_PREFIXES = (
    "export ANTHROPIC_API_KEY=", "ANTHROPIC_API_KEY=",
    "ANTHROPIC_API_KEY:", "x-api-key:",
    "Authorization: Bearer", "Authorization:",
    "Bearer", "bearer",
)

def _normalise_api_key_paste(raw: str) -> str:
    raw = raw.strip()
    raw_lower = raw.lower()
    for prefix in _API_KEY_PASTE_PREFIXES:
        if raw_lower.startswith(prefix.lower()):
            raw = raw[len(prefix):].lstrip(" \t")
            break
    # Strip a single layer of wrapping quotes (.env: `KEY="sk-ant-..."`).
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()
    return raw

@router.post("/api-key")
def claude_auth_set_api_key(body, current_user, db):
    raw = _normalise_api_key_paste(body.api_key)
    if not raw.startswith("sk-ant-"):
        raise HTTPException(400, "...console.anthropic.com/settings/keys")
    # ... get-or-create IntegrationConfig ...
    _revoke_other_claude_credentials(db, config.id, tid, keep="api_key")
    store_credential(..., credential_key="api_key", credential_type="api_key")
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

`store_credential` revokes prior active credentials **with the same `credential_key`** — but OAuth uses `credential_key='session_token'` and this path uses `credential_key='api_key'`, so they live in disjoint key namespaces. Without an explicit cross-key revoke, switching flows would leave the other path's row active and downstream readers would silently prefer it. The endpoint calls `_revoke_other_claude_credentials(..., keep='api_key')` before storing, and the OAuth path does the symmetric revoke with `keep='session_token'`. Single active credential at any time.

The `_tenant_has_claude_credential` connection-state check now accepts either credential_key, so `/status` and `/start` correctly report `connected: true` immediately after a successful API-key store.

Downstream consumers (`apps/code-worker/cli_executors/claude.py` and the code-task flow in `workflows.py`) now branch on the `(value, kind)` tuple returned by `_fetch_claude_credential`:
- `kind == 'oauth'` → sets `CLAUDE_CODE_OAUTH_TOKEN` env var (Bearer for claude.com)
- `kind == 'api_key'` → sets `ANTHROPIC_API_KEY` env var (Console billing path)

`cli_session_manager.subscription_missing` for `claude_code` accepts either `session_token` or `api_key`, so the API-key path actually drives requests instead of falling back to the local agent.

## Tests

Cases in `apps/api/tests/api/v1/test_claude_auth_api_key.py`:

- Happy path stores `credential_type='api_key'` and includes the caller's `tenant_id`.
- IntegrationConfig query filter includes a `tenant_id` predicate (tenant isolation regression guard).
- Non-Anthropic prefix (OpenAI `sk-proj-...`) → 400 with pointer to `console.anthropic.com`.
- Paste-prefix normalisation: `.env`-line, `export ANTHROPIC_API_KEY=`, `x-api-key:` header, `Bearer ` / `BEARER` (case-insensitive), double-quote wrapping, YAML extra-whitespace.
- `min_length=20` boundary: 19 chars → 422; 20 chars with bad prefix → 400 (proves the length check fires before prefix check and not at e.g. 10).
- Existing `IntegrationConfig` reused (not duplicated).
- `_normalise_api_key_paste` is idempotent: f(f(x)) == f(x).

All tests use `monkeypatch.setattr` so module-level mutations are torn down at test teardown — no pollution of other tests in the same pytest process.

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

- Doesn't fix the subscription-OAuth flow (still architecturally broken; option b is the real fix when needed — PR #471 ships that)
- Doesn't add the UI input (PR #471 ships that, chained off this branch)

## References

- Session diagnosis of the OAuth subprocess hang
- `apps/api/app/services/orchestration/credential_vault.py` `store_credential`
- `apps/api/app/models/integration_config.py`
