# Claude OAuth: stdin-forward verification code (option b)

**Date:** 2026-05-14
**Branch:** `feat/claude-auth-stdin-forward`
**Status:** Implementing

## TL;DR

Fix the Claude subscription-OAuth flow that's been broken since claude CLI v2.x. The CLI no longer completes OAuth via a localhost callback (we have no browser inside the api container) — it prints a verification URL, then **blocks at a `Paste code here >` stdin prompt** waiting for a code the user got from claude.com.

This PR wires the missing piece: a `/submit-code` endpoint that pipes the user's pasted code to the running subprocess's stdin + a UI input to capture the paste. Old `/start` and `/status` endpoints unchanged in shape but the underlying `_run_login` is rewritten so reading the URL doesn't consume the stdin pipe.

## What the user actually does after this

1. Click "Connect with Anthropic" in the IntegrationsPanel → UI POSTs `/start`.
2. Server spawns `claude auth login --claudeai`, captures URL on stdout, opens browser to it.
3. User signs in on claude.com, gets a verification code.
4. **NEW:** UI shows a "Paste the code from claude.com" input (only while `status == 'pending'`).
5. User pastes → UI POSTs `/submit-code` → server writes to subprocess stdin + closes stdin.
6. Claude CLI completes the handshake and exits 0.
7. Server reads credentials from `CLAUDE_CONFIG_DIR`, stores in vault.
8. UI polls `/status` → `connected: true`.

## What was broken before

`_run_login` called `proc.communicate(timeout=5)` to grab the URL. `communicate()` waits for the subprocess to finish AND CLOSES the stdin pipe. So:

- The URL came through (via `TimeoutExpired.output`) BUT
- The subprocess could no longer receive any input via stdin
- `_run_login` then called `proc.communicate(timeout=300)` a second time, which just waited for the subprocess that was blocked on stdin reads it could never satisfy
- 300s timeout → status="failed" with no URL surfaced to the UI
- User saw an indefinite spinner

## What this PR rewrites

`apps/api/app/api/v1/claude_auth.py`:

- **`ClaudeLoginState`** — added `_output_buf: list` and `_code_submitted: threading.Event` for the new lifecycle.
- **`_run_login`** completely rewritten:
  - `Popen(stdin=PIPE, ...)` so we have a writable handle.
  - Background reader thread drains stdout line-by-line into `_output_buf`. Detects the URL on the way through, promotes status to `'pending'` the instant a URL appears.
  - Main thread polls `_code_submitted` for up to 10 min (the user has to fetch a code from claude.com — this is human-scale time).
  - On submit: write code + `\n` to stdin, close stdin, `proc.wait(timeout=60)` for the handshake to finalize.
  - On success: `_persist_credentials` reads from `CLAUDE_CONFIG_DIR`, stores in vault.
- **New `submit_code` method** on `ClaudeAuthManager` — normalises the paste (strips wrapping whitespace + quotes), writes to subprocess stdin, signals the event.
- **New `/submit-code` route** — accepts `{code: "..."}`, returns the updated state.
- **`_serialize_state`** — adds `awaiting_code: bool` so the UI doesn't need to know the state-machine vocabulary; renders the paste input whenever this is true.

`apps/web/src/services/integrationConfigService.js`:

- New `claudeAuthSubmitCode(code)` mirroring the existing `geminiCliAuthSubmitCode`.
- New `claudeAuthSetApiKey(apiKey)` for option (a) from PR #470.

`apps/web/src/components/IntegrationsPanel.js`:

- New `claudeCode`, `claudeApiKey`, `claudeShowApiKey` state.
- New `handleClaudeSubmitCode` and `handleClaudeSubmitApiKey` handlers.
- Replaced the claude_code panel with the two-stage UI:
  - **Stage 1 (`status == 'starting'`)** — "Starting Claude login…" info alert.
  - **Stage 2 (`status == 'pending'`)** — "Step 2 of 2" info alert + paste-code input + Submit button + fallback "Open URL manually" link.
  - **Stage 3 (`status == 'submitting'`)** — "Finishing OAuth handshake…" info alert.
  - **Connected** — success alert + Reconnect button.
  - **Failed** — error alert with server-supplied detail.
  - **Below the primary path** — a "Or use an API key" disclosure that reveals an `<input type="password">` for option (a).

## State machine

```
idle ──/start──▶ starting ──reader sees URL──▶ pending
                     │                              │
                     │                              /submit-code
                     │                              │
                     ▼                              ▼
                  failed                       submitting
                                                   │
                                          proc.wait + persist
                                                   │
                                                   ▼
                                              connected
```

Cancellation lands `cancelled` from any non-terminal state.

## Out of scope

- Tests — should be in the PR but the rebuild-all deploy is in flight and the user is blocked NOW. Coming as a follow-up commit on this branch before merge.
- Removing the OAuth subprocess entirely in favor of direct API calls to `console.anthropic.com/login/oauth` — bigger rewrite, the subprocess works once it gets stdin.

## Risks

- **Subprocess can deadlock if stdout buffer fills before we drain it.** Reader thread drains line-by-line, so this shouldn't happen for normal output. If it does, the 10-min paste deadline catches it.
- **`_OAUTH_PASTE_DEADLINE_SECONDS` is 10 min.** Long enough for "open URL → sign in → copy code" but not so long that a stale subprocess hangs around forever. claude CLI's own server-side code TTL is shorter; we'll see failures from claude.com before our timeout if the user dawdles past the CLI's window.
- **Race between `/submit-code` and subprocess exit.** Caught explicitly: we check `proc.poll()` before writing and return 400 if the subprocess already died.

## References

- PR #470 (option a — API-key path)
- session log of the cli-v0.7.4 e2e where this surfaced
