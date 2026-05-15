# OAuth: preserve refresh_token when provider doesn't rotate it

**Date:** 2026-05-14
**Branch:** `fix/oauth-refresh-token-preserve`
**Status:** Implementing

## TL;DR

`_update_stored_tokens` was destroying the long-lived `refresh_token` on every successful refresh, leaving tenants with one valid access token and no way to mint another. Eventually the access token expired and Luna started reporting "your gmail token expired" with no recovery path short of re-consenting. The fix narrows the revoke filter to only the credential keys we're actually replacing.

## Root cause

`apps/api/app/api/v1/oauth.py:_update_stored_tokens` (called from the `/internal/token/{integration_name}` auto-refresh path):

```python
old_creds = (
    db.query(IntegrationCredential)
    .filter(
        IntegrationCredential.integration_config_id == integration_config_id,
        IntegrationCredential.tenant_id == tenant_id,
        IntegrationCredential.credential_key.in_(["oauth_token", "refresh_token"]),  # ← always both
        IntegrationCredential.status == "active",
    )
    .all()
)
for old_cred in old_creds:
    revoke_credential(db, credential_id=old_cred.id, tenant_id=tenant_id)

store_credential(..., credential_key="oauth_token", plaintext_value=access_token, ...)
if refresh_token:
    store_credential(..., credential_key="refresh_token", plaintext_value=refresh_token, ...)
```

Google does **not** rotate `refresh_token` on every refresh — it returns one on initial consent and sporadically on security rotations. A normal refresh response is just `{access_token, expires_in}`. So:

1. First successful refresh after consent
2. `_refresh_access_token` returns `{"access_token": "..."}` with no `refresh_token`
3. `_update_stored_tokens` is called with `refresh_token=None`
4. Filter selects both old `oauth_token` AND old `refresh_token` rows
5. Both get revoked
6. New `oauth_token` is stored
7. `refresh_token` store is skipped (None param)
8. State: zero active refresh_tokens. The next refresh attempt finds no refresh_token, falls through, returns the stale access_token until it expires.

Caught while debugging Luna's "your gmail token expired" report for tenant `147f3f50-...`. DB query confirmed: zero active refresh_tokens across gmail/google_calendar/google_drive for that tenant; only revoked ones from initial consent.

**6 tenants are affected today** (query: configs with `enabled=true` for gmail/calendar/drive/outlook where no active refresh_token exists).

## Fix

Narrow the IN-list to only the credential keys we're actually replacing:

```python
keys_to_revoke = ["oauth_token"]
if refresh_token:
    keys_to_revoke.append("refresh_token")

old_creds = db.query(IntegrationCredential).filter(
    ...
    IntegrationCredential.credential_key.in_(keys_to_revoke),
    ...
).all()
```

Microsoft refresh-token-rotation IS supported in this codebase (`_refresh_access_token` propagates `refresh_token` from the response when present), so when Microsoft does rotate we still revoke + swap correctly. Behavior is now:

- **No new refresh_token in response** → revoke only `oauth_token`, store new `oauth_token`, leave `refresh_token` row untouched.
- **New refresh_token in response** (Microsoft rotation) → revoke both, store both. Old refresh_token cannot be reused.

## Recovery for affected tenants

The fix prevents new breakage. Tenants whose refresh_tokens were already destroyed need to re-consent — there's no way to recover the refresh_token from a third-party provider after revocation. The OAuth init at `oauth.py:354` already requests `access_type=offline&prompt=consent` for Google, so the next consent will mint a fresh refresh_token that the fixed code will preserve correctly.

## Tests

`apps/api/tests/api/v1/test_oauth_refresh_token_preserve.py`:

1. **`test_refresh_without_new_refresh_token_preserves_existing`** — exercises Google's normal case. Asserts the IN-list contains only `oauth_token`, the existing refresh_token row is NOT revoked, and only one new credential is stored. This is the regression guard: with the buggy code the IN-list would contain both keys and the assertion fails.
2. **`test_refresh_with_rotated_refresh_token_swaps_both`** — exercises Microsoft's rotation case. Asserts the IN-list contains both keys, both old rows revoked, both new rows stored.
3. **`test_update_swallows_db_exceptions`** — confirms the helper still swallows DB exceptions so a refresh failure doesn't 500 the internal token endpoint.

Tests use a smart DB mock that introspects SQLAlchemy's IN-clause via the `BindParameter.value` on each filter() arg — works across SQLAlchemy versions without coupling to internals.

All 3 tests pass.

## Files

- `apps/api/app/api/v1/oauth.py` — narrowed revoke filter in `_update_stored_tokens`
- `apps/api/tests/api/v1/test_oauth_refresh_token_preserve.py` — new regression tests
