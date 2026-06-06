# Claude Code Subscription Worker Auth — Native Login Model

**Date:** 2026-05-29 · **Status:** Backfilled (shipped)
**PRs:** #731, #733, #732, #734
**Files:** `apps/code-worker/cli_executors/claude.py`, `apps/code-worker/cli_executors/claude_interactive.py`, `apps/api/app/api/v1/claude_auth.py`, `apps/code-worker/README.md`, `docker-compose.yml`

> Scope: the **auth model** for subscription Claude Code in the code-worker — how a native subscription session is obtained, stored, and selected per tenant. The *prompt-submission mechanics* (PTY keystroke timing, two-phase submit, answer-file scraping, freeze recovery) are documented separately in [`2026-05-30-claude-code-interactive-prompt-submission.md`](2026-05-30-claude-code-interactive-prompt-submission.md) — this doc complements, not repeats, it.

## Problem / context

Around 2026-05-29 Anthropic **blocked `claude setup-token` and `claude -p` (print mode) for Claude *subscription* (OAuth) accounts** (an Anthropic-side change, not visible in our code). That broke two assumptions the platform was built on:

1. The code-worker's Claude executor ran every chat turn as `claude -p --output-format json` with a per-tenant `sk-ant-oat01-…` token exported as `CLAUDE_CODE_OAUTH_TOKEN`. For a subscription account that token model no longer works.
2. The web `/integrations` "Connect with Anthropic" flow (`claude_auth.py::_run_login`) spawned `claude setup-token` and waited for the `https://claude.com/…` verification URL it prints. setup-token no longer emits that URL for subscription accounts, so the flow hung forever at "Starting Claude login…" (reproduced live in Chrome; `claude` v2.1.148 in the api container).

The only path that still works for a subscription account is a **native interactive login** (`claude auth login --claudeai`) that writes a `.credentials.json` session into a HOME, driven through an interactive TTY rather than `-p`. API-key tenants are unaffected and stay on `-p` + `ANTHROPIC_API_KEY` (Console billing).

## What shipped

**#731 — interactive PTY runner + worker HOME selection (worker engine).**
Adds `claude_interactive.py` (a stdlib-only PTY-backed runner) and wires `execute_claude_chat` to drive a native Claude Code TTY instead of `-p`. Gated by `CLAUDE_CODE_EXECUTION_MODE` (`print` default unchanged; `interactive`/`pty`/`native` opt-in) and only for `kind == "oauth"` credentials — **API-key tenants stay on print mode even when the worker globally enables interactive**. For native auth the executor **pops `CLAUDE_CODE_OAUTH_TOKEN`** (and always drops inherited `ANTHROPIC_API_KEY`) so the stored `.credentials.json` is the sole credential. `CLAUDE_CODE_INTERACTIVE_HOME` selects the HOME the session is tied to: `tenant` (per-tenant HOME on the workspaces volume) or `worker`/`codeworker` (`/home/codeworker`, override via `CLAUDE_CODE_WORKER_HOME`) for a worker that was authenticated once. README documents the three new env vars. Default mode stays `print`, so production behavior was unchanged until the flags were flipped.

**#733 — web connect via native auth (control plane).**
`_run_login` switches from `claude setup-token` to **`claude auth login --claudeai`** (dropping inherited `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` so it does the claude.ai subscription login, mirroring the worker). Headless it prints the same authorize-URL → paste-code shape the manager already drives, so **no frontend change**. On success the CLI writes a native `.credentials.json` under `CLAUDE_CONFIG_DIR`; new `_install_worker_credentials` **atomically copies it (mkstemp + `os.replace`, mode 0600) into the code-worker's shared `claude_sessions` volume** so interactive PTY sessions read it from `/home/codeworker/.claude/.credentials.json`. `docker-compose.yml` mounts `claude_sessions:/home/codeworker/.claude` on the **api** service — both containers run as uid 1000, so the api can write the file. The global `CLAUDE_CODE_EXECUTION_MODE=interactive` flip was deliberately **not** bundled here (a scope escalation across all tenants); decoupling it is what kept this PR bounded.

**#732 — pre-complete onboarding for the interactive TTY HOME (the silent-login enabler).**
Interactive `claude` runs a first-run onboarding wizard on any HOME lacking `hasCompletedOnboarding`; at "Select login method" it starts a *fresh* OAuth login the headless PTY can't finish — so a HOME that is genuinely logged in (`claude auth status` → `loggedIn: true`, `claude.ai`, Max) still failed with `native subscription auth is not configured for HOME=…`. `_ensure_claude_onboarding(home, trusted_cwd)` seeds `$HOME/.claude.json` with `hasCompletedOnboarding: true` plus per-cwd trust flags (`hasTrustDialogAccepted`, `hasCompletedProjectOnboarding`, `projectOnboardingSeenCount ≥ 1`) right before the TTY spawns, so Claude uses the stored credential silently. It is **best-effort, idempotent, never raises**, writes atomically at 0600 (the file is secret-grade), and only seeds a HOME that was *deliberately* resolved — never the inherited fallback HOME, so a `tenant_home_dir()` failure can't mutate the container HOME. (The folder-trust realpath keying noted in the code is a later refinement.)

**#734 — per-tenant routing through the worker credential (no global flip).**
`get_connected_integrations` marked `claude_code` connected only when a vault credential existed, but the connect flow stored none — so the picker hid Claude and chat fell through to Gemini. Fix: the connect flow (`_install_worker_credentials`) stores a **sentinel `session_token = "__native_worker_login__"`** — never a usable token — so the integration reads connected + routable. The executor detects that exact sentinel (`_native_worker_login = kind == "oauth" and token == "__native_worker_login__"`) and **forces the interactive PTY path + worker HOME for that tenant only**, with no global `CLAUDE_CODE_EXECUTION_MODE` flip and the `kind == "oauth"` gate keeping API-key tenants on print mode. The sentinel never reaches Anthropic (native interactive pops the token). Per Luna's safeguard, if the sentinel is set but the worker volume credential is missing, the turn returns an explicit "Claude Code worker auth missing — reconnect" error rather than silently faking connectivity by falling back to another CLI.

**Resulting auth-selection matrix** (in `execute_claude_chat`):

| Credential | Routing | CLI invocation | Token env |
|---|---|---|---|
| `kind == "api_key"` | print | `claude -p` | `ANTHROPIC_API_KEY` set, `CLAUDE_CODE_OAUTH_TOKEN` popped |
| `kind == "oauth"`, sentinel `__native_worker_login__` | interactive (forced per-tenant) | native TTY via PTY | both tokens popped → stored `.credentials.json` |
| `kind == "oauth"`, real token + `CLAUDE_CODE_EXECUTION_MODE=interactive` | interactive | native TTY via PTY | `CLAUDE_CODE_OAUTH_TOKEN` popped (native auth) |
| `kind == "oauth"`, print mode | print (legacy) | `claude -p` | `CLAUDE_CODE_OAUTH_TOKEN` set |

## Outcome

The four PRs together replaced the now-dead `setup-token`/`sk-ant-oat01` model for subscription Claude with a native-session model: connect once in the browser → the api copies the native `.credentials.json` into the worker's shared volume → a sentinel makes the integration read connected and routable → the worker selects the interactive PTY + worker HOME per tenant and runs the session with onboarding pre-seeded so it uses the stored credential silently. API-key tenants are untouched throughout. Known follow-up at the time of writing: the `claude_sessions` volume shares trivially under docker-compose but needs a **ReadWriteMany PVC** to share across api + code-worker pods on Helm/K8s (flagged, not implemented). The prompt-submission and freeze-recovery work that made the *turn itself* reliable landed in #735–#744 (see Related).

## Related

- [`2026-05-30-claude-code-interactive-prompt-submission.md`](2026-05-30-claude-code-interactive-prompt-submission.md) — sibling doc: PTY keystroke submission, two-phase submit, answer-file scrape (the mechanics this doc deliberately omits)
- [`2026-06-01-claude-interactive-longtask-watchdog-fix.md`](2026-06-01-claude-interactive-longtask-watchdog-fix.md) — long-task/freeze watchdog tuning (#743/#744 lineage)
- [`2026-05-16-oauth-reconnect-token-format-mismatch.md`](2026-05-16-oauth-reconnect-token-format-mismatch.md) — the prior `setup-token` token-shape fix this work supersedes for subscription accounts
- Memory: `claude_code_subscription_auth` — the operational record (block details, deploy gotchas, multi-turn verification lessons)
