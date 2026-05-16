# Gemini CLI OAuth Reconnect — exitCode 41 root cause + fix

**Date:** 2026-05-16
**PR branch:** `fix/gemini-cli-auth-exitcode-41`
**Hit by:**
  - `saguilera` (tenant `87b0ce48`) — earlier reconnect attempt
  - `thesimondigitalnomad` (tenant `3d314d2d`) — fresh account at 22:00 UTC

## Symptom

Frontend posts to `/api/v1/gemini-cli-auth/start`, backend spawns a `gemini`
subprocess in a tenant-scoped temp `HOME`, captures the verification URL,
returns to the UI. User opens the URL, completes Google consent, copies the
auth code from `https://codeassist.google.com/authcode`, pastes it into the
UI. UI POSTs `/submit-code`, backend writes `code + "\n"` to the
subprocess's pty master. ~80s later the subprocess dies with exitCode 41:

```
chunk-7VVHSNDQ.js:274015 at async createContentGenerator
chunk-7VVHSNDQ.js:273972 at async Config.refreshAuth
chunk-7VVHSNDQ.js:336111 at async main
gemini-QSTQ2DBG.js:15890 { exitCode: 41 }  Failed to authenticate with user code.
```

A vault row is created with `keys=['session_token']` (junk shape from the
caller's previous flow), but every later use 401s.

## Root cause

Exit code 41 maps to `FatalAuthenticationError` in the gemini-cli bundle
(`chunk-JEW7ZIWE.js:25710`, `FatalAuthenticationError extends FatalError`
with `exitCode = 41`). The throw site is `oauth2.ts::initOauthClient` —
after `maxRetries = 2` failed calls to `authWithUserCode(client)`.

`authWithUserCode` runs an **interactive PKCE redirect-based code flow**:

1. Generate `codeVerifier` (PKCE S256), pick a random `state`.
2. Build authUrl pointing at `redirect_uri =
   https://codeassist.google.com/authcode` with the gemini-owned client_id
   `681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j`.
3. Print `Please visit the following URL...` then prompt
   `Enter the authorization code:` via `readline.question`.
4. `client.getToken({ code, codeVerifier, redirect_uri })` exchanges the
   authorization code at Google's token endpoint.

If step 4 fails (any reason: bad code, expired code, codeVerifier mismatch
across retries, wrong redirect_uri echoed back) → `authWithUserCode` returns
`false` → retry loop runs once more (and asks the user for ANOTHER code
they don't have) → second attempt also returns false → throws
`FatalAuthenticationError`. Subprocess exits 41.

**Why both users hit it today, on a flow that used to work:**

The path is structurally fragile. We are coordinating four concurrent
state machines:

  1. The gemini subprocess (its own PKCE `codeVerifier` lifetime, retry
     loop, alt-screen rendering, readline state machine).
  2. The Python pty reader (two threads racing on the same `master_fd`).
  3. The frontend (polling `/status`, separately POSTing `/submit-code`).
  4. The user (manually pasting between two browser tabs, prone to
     pasting the URL or whitespace-laden text).

Any of these failure modes returns the exact same error:

  - **Expired code:** Google's authcode is short-lived (~minutes). Subprocess
    spawn + URL capture + user reads URL + completes consent + copies code +
    pastes into our UI + we POST `/submit-code` + we write to pty + readline
    decodes the line + gemini exchanges with Google — total >>30s easily
    and includes user think-time. Empirically the user took ~80s.
  - **codeVerifier mismatch on retry:** if anything causes
    `authWithUserCode` to throw before `getToken` returns success (e.g.
    pty write interleaving, partial line buffering, anti-CSRF state
    mismatch), the retry generates a fresh codeVerifier. The code the user
    pastes was bound to the OLD codeVerifier → unconditionally rejected.
  - **Wrong artifact pasted:** the codeassist.google.com/authcode page
    shows the code with framing whitespace and a copy button; some users
    paste extra characters or the entire URL fragment.
  - **gemini-cli 0.42.0 regression:** `apps/api/Dockerfile:61` does
    `npm install -g @anthropic-ai/claude-code @google/gemini-cli`. The
    Docker image is rebuilt frequently — it floats on `@latest`. The
    James-era vault row was written when 0.38.1 was current; 0.42.0 may
    have changed prompt strings, codeVerifier rotation, or PKCE redirect
    URI semantics relative to that working state.

In short: **the subprocess+pty paste-code flow is the wrong mechanism**.
We are roundtripping through a child process to do what is fundamentally
just a 4-line OAuth dance the api server is already perfectly capable of
performing directly. Every concurrency hazard above disappears if we own
the flow end-to-end.

## Fix — Option B (own the OAuth flow, write `oauth_creds.json` for gemini)

Mirror the gemini-cli OAuth dance ourselves in the api process:

1. **`POST /start`**

   - Generate `code_verifier` (high-entropy URL-safe base64, 64 bytes).
   - Compute `code_challenge = SHA256(code_verifier)` base64url-NoPad.
   - Generate `state` (32 bytes hex).
   - Build the authUrl pointing at
     `redirect_uri = https://codeassist.google.com/authcode` with:
       * `client_id` — the installed-app client embedded in the
         gemini-cli npm bundle (`681255809395-…apps.googleusercontent.com`)
       * `scope =`
         `https://www.googleapis.com/auth/cloud-platform`
         ` https://www.googleapis.com/auth/userinfo.email`
         ` https://www.googleapis.com/auth/userinfo.profile`
       * `access_type=offline`
       * `code_challenge_method=S256`
       * `prompt=consent` (force refresh_token issuance)
   - Persist `(login_id, tenant_id, code_verifier, state, created_at)` in
     an in-memory `GeminiAuthManager` dict keyed by `tenant_id`.
   - Return `{verification_url: authUrl, status: 'pending', login_id, ...}`.
   - **No subprocess spawn.** No `HOME` tempdir. No pty.

2. **`POST /submit-code`**

   - Look up tenant's pending state. 404 if none.
   - `code = body.code.strip()`. Reject empty.
   - POST to `https://oauth2.googleapis.com/token` with form-urlencoded:
       * `grant_type=authorization_code`
       * `code=<user-pasted>`
       * `code_verifier=<verifier>`
       * `client_id=...`
       * `client_secret` — the matching installed-app secret from the
         gemini-cli bundle (Google's installed-app client model:
         secret is shipped publicly; not a real secret)
       * `redirect_uri=https://codeassist.google.com/authcode`
   - Parse `{access_token, refresh_token, scope, token_type,
     expires_in, id_token}`.
   - Reject if `refresh_token` missing — we need it for long-lived use.
   - Compute `expiry_date = now_ms + expires_in*1000` (gemini's
     `oauth_creds.json` format).
   - Persist the JSON blob to the encrypted vault under
     `integration_name='gemini_cli'`, `credential_key='oauth_creds'`
     (matches the existing reader path in code-worker).
   - Also persist `oauth_token` (access_token) and `refresh_token`
     fields under their own keys, mirroring today's `_persist_creds`
     behaviour for backwards-compat with consumers reading individual
     keys.
   - Set `state.status = 'connected'`, `state.connected = True`,
     `state.completed_at`.
   - Return the serialized state.

3. **`POST /cancel`** → drop the in-memory state.

4. **`POST /disconnect`** → unchanged (still revokes vault rows).

5. **Code-worker side:** when the worker spawns `gemini` for an actual
   chat turn, write the `oauth_creds.json` blob from the vault into
   `${tenant_home}/.gemini/oauth_creds.json` before exec. The existing
   `_fetch_integration_credentials → write oauth_creds` path already
   handles this; no change required here.

### Blast radius

- **One file changed (mostly rewritten):**
  `apps/api/app/api/v1/gemini_cli_auth.py`. Same routes, same
  request/response shapes. No frontend change. No code-worker change.
  No env var change. No migration.
- **No new dependencies.** We POST to `oauth2.googleapis.com/token`
  with `httpx`, already used elsewhere in the api.
- **No Helm/Terraform drift** (no env vars added).
- **Tests:** `apps/api/tests/api/v1/test_gemini_cli_auth_owned_flow.py`
  with happy-path, sad-path (bad code → Google 4xx), and idempotency
  (re-submit after success is a no-op) cases.

### Why not Option A (different gemini subcommand)

There isn't one. `gemini` has no `setup-token`-style command that prints
a credential to stdout. `gemini auth` doesn't exist as a top-level
command. The only entry points are the default interactive REPL (what
we spawn today) and `gemini -p '...'`. Both go through the same
`initOauthClient → authWithUserCode/authWithWeb` machinery. Option A is
not available.

### Why not Option C (pre-resolve on api side using browser-redirect server)

The `authWithWeb` flow gemini-cli uses with a browser binds the OAuth
callback to `http://127.0.0.1:<random-port>` on the **api container's**
loopback. The user's browser cannot reach that. Would require either a
tunnel or pinning the api container to a stable external callback
URL+port, both of which are bigger refactors than Option B.

### Why not Option D (pin older gemini-cli)

The api container only uses gemini for OAuth bootstrap. After Option B
ships, the api doesn't spawn gemini at all during auth — it just writes
the resulting `oauth_creds.json` and lets the **code-worker** (which is
where gemini actually runs for chat turns) read it. Pinning would mask
the structural fragility without fixing it; once a future Gemini-CLI
release rotates client_id or PKCE-redirect-URI we'd be stuck again. The
oauth_creds.json schema we write is the same shape gemini's
`google-auth-library` has consumed for years — far more stable than the
CLI's interactive flow.

## Test plan

- `tests/api/v1/test_gemini_cli_auth_owned_flow.py`:
  - **Happy path:** `/start` returns a Google authUrl + PKCE
    parameters; `/submit-code` with a mocked Google token endpoint
    returning `{access_token, refresh_token, expires_in, ...}` writes
    the expected vault rows and returns `status='connected'`.
  - **Sad path:** Google returns `{error: 'invalid_grant'}` (expired
    code) → `/submit-code` returns `status='failed'` with a redacted
    error message, no vault row.
  - **Idempotency:** posting `/submit-code` again after success is a
    no-op — returns `status='connected'`, doesn't re-write vault rows.
- `python -m py_compile apps/api/app/api/v1/gemini_cli_auth.py` clean.

## Out of scope

- Code-worker session refresh on `expiry_date` < now. Existing helper
  (used for the now-defunct device-flow tokens) handles refresh via
  the standard Google refresh-grant. Nothing in this PR.
- Pinning gemini-cli version in the Dockerfile.
- Frontend copy changes (the existing "Paste the code from Google" UI
  message already matches what users see on the codeassist.google.com
  page).
