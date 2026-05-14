# `/login/device` SPA route for alpha CLI device-auth flow

**Date:** 2026-05-14
**Author:** Claude (opus) at user request
**Status:** Implementing
**Branch:** `feat/web-login-device-page`
**Task:** #201

## TL;DR

`alpha login` from the CLI calls `POST /api/v1/auth/device-code` which returns a `verification_uri` of `/login/device?user_code=XXXX-XXXX`. The CLI prints that URL and tells the user to open it. **The SPA has never had a matching React Router route**, so every fresh device-flow login hits a 404 — the CLI's device-flow has effectively never worked end-to-end for any new user.

This PR adds the missing page so the loop closes.

## Problem

Verified during the cli-v0.7.4 end-to-end test on 2026-05-13:

```
$ alpha login
First copy your one-time code: 5ZEU-G55U
Then open: /login/device?user_code=5ZEU-G55U
  ⠹ waiting for approval...
```

User clicks the URL. Browser hits `https://agentprovision.com/login/device?user_code=5ZEU-G55U`. React Router has no matching route, falls through to the catch-all, console shows:

```
main.cfcad2b4.js: No routes matched location "/login/device?user_code=5ZEU-G55U"
```

CLI polls forever until the 5-minute device-code TTL expires. The user's existing keychain token (from a previous `alpha login` or web sign-in) is what's been carrying every CLI user through; first-time device-flow has been broken.

## Server contract (already shipped, only the SPA half is missing)

`apps/api/app/api/v1/auth.py:626` — `/api/v1/auth/device-code` returns:

```json
{
  "user_code": "5ZEU-G55U",
  "device_code": "...",
  "verification_uri": "/login/device",
  "verification_uri_complete": "/login/device?user_code=5ZEU-G55U",
  "expires_in": 300,
  "interval": 2
}
```

`apps/api/app/api/v1/auth.py:652` — `/api/v1/auth/device-approve` accepts `{user_code}` and returns `{approved: true}`. Requires `current_user`. Normalises the code (strips spaces + dashes, uppercases). Returns 400 on malformed code, 404 on expired/missing, 409 on already-approved.

## Implementation

### `apps/web/src/pages/DeviceLoginPage.js` (new)

- Reads `user_code` from `useSearchParams()`.
- Normalises it (matching the server's strip-spaces-and-dashes-uppercase logic) so a paste-from-screenshot still renders cleanly.
- Pre-flight check: if missing or malformed, skip to the error state without firing a POST.
- Renders the code prominently (`display-6` mono with letter-spacing), the signed-in user's email, and a primary "Approve sign-in" button + cancel link.
- On submit: `axios.post('/api/v1/auth/device-approve', {user_code})`. The page never sets an Authorization header itself — the axios global interceptor adds it via the same path the rest of the SPA uses.
- Error states map server statuses to actionable copy:
  - 404 → "expired or never issued, run `alpha login` again"
  - 409 → "already approved, get a fresh code"
  - 400 → "format invalid"
  - else → surface `detail` for grep-ability in bug reports
- Success state: "Return to your terminal" message — no auto-close because we have no way to message the CLI from here.

### `apps/web/src/App.js`

Add one line:

```jsx
<Route path="/login/device" element={<ProtectedRoute><DeviceLoginPage /></ProtectedRoute>} />
```

Wrapped in `<ProtectedRoute>` because the approve endpoint needs `current_user`. Unauthenticated users get the standard redirect-to-login flow that already exists for the dashboard routes, with a return-to that brings them back here after sign-in.

### Tests (jest)

`apps/web/src/pages/__tests__/DeviceLoginPage.test.js`:
1. Renders the user_code from the query string in the prominent display.
2. Normalises a lowercase / dashless query (e.g., `?user_code=5zeug55u`) to the canonical `5ZEU-G55U`.
3. Errors on missing `user_code` query param without firing a POST.
4. Errors on malformed `user_code` without firing a POST.
5. POSTs to `/api/v1/auth/device-approve` with the canonical code on approve.
6. Maps 404 → expired-code error message.
7. Maps 409 → already-approved error message.

## Out of scope

- **Auto-close / desktop-notify the terminal on success.** Out of scope; there's no IPC. The CLI poll loop will pick up the approval within `interval` seconds (2s by default) and print its own success message.
- **CSRF token.** The approve endpoint runs under the same JWT-bearer auth as every other tenant-scoped POST; the SPA already trusts the bearer for state-changing calls. Adding CSRF here without adding it everywhere would be cargo-cult.
- **Rate limiting.** Already on the server (`@limiter.limit("10/minute")` at `auth.py:653`).

## Verification

- 7 jest cases pass under `npm test -- DeviceLoginPage`
- Manual smoke: `alpha login` → click the URL → see code → approve → return to terminal → CLI completes within ~2s.
- The deploy queue currently has the pre-build-prune fix (PR #463) ahead of this — once that merges + this merges + deploy queue drains, the page is live on `agentprovision.com`.

## References

- PR #442 + #445 — long-lived CLI sessions (refresh tokens — the OTHER way users get authenticated, which has been masking this device-flow gap)
- PR #463 — pre-build disk-free step that prevents the deploy queue from wedging on Rust builds, prereq for this PR landing in prod
- `apps/api/app/api/v1/auth.py:534-720` — full device-flow server contract
