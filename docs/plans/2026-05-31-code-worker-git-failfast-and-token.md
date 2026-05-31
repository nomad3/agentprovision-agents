# Code-worker git auth: wire the per-tenant OAuth token + fail-fast (no 25-min hang)

**Date:** 2026-05-31
**Status:** Plan v2 (overnight; Codex + Luna reviewed v1, folded below)
**Owner:** Simon
**Trigger:** "Ask Luna to pull my work repos" → Luna *gets stuck* 25 min then `exit -9` (`latency_ms ≈ 1500284`). Normal turns + MCP-tool tests work — this is git-auth-specific, NOT the #743/#744 startup freeze.

## Root cause (measured)

The worker **has** the user's GitHub OAuth token (the `/integrations` connection): `_fetch_github_token()` resolves it and `GET /oauth/internal/token/github` returns **HTTP 200**. The chat path (`execute_chat_cli`, workflows.py:1186-1199) even fetches it, sets `GITHUB_TOKEN`, and runs `gh auth login --with-token`.

**But there is NO git credential wiring anywhere** — `grep` for `setup-git` / `credential.helper` / `insteadOf` across `apps/code-worker/` is empty. So:
1. `gh` is authenticated, but **git is not configured to use it**. A plain `git clone https://github.com/<repo>` has no credential helper → git prompts `Username for 'https://github.com':` on the PTY.
2. **No non-interactive guard** (`GIT_TERMINAL_PROMPT`/`GIT_ASKPASS`/`GIT_SSH_COMMAND` all unset) → that prompt **blocks for the full `timeout=1500`** → SIGKILL = `exit -9`.
3. The static `GITHUB_TOKEN` falls back to the literal `ghp_placeholder` (runner `.env` lacks the var), and `entrypoint.sh:31` fake-auths `gh` with it.

So the OAuth token the user connected is present but **unused for clones**, and a credential-less clone **hangs instead of failing**.

## Goal

(a) **Authorized pulls succeed** — wire the per-tenant OAuth token as git's credential for github.com, in *Claude's* turn env (HOME-correct). (b) **Everything else fails in seconds**, never hangs. (c) Stop fabricating a fake token.

## Changes

### A. Wire the OAuth token into the turn's git (the enabler) — `cli_executors/claude.py`
Per-turn, per-subprocess `env` dict only (NOT `os.environ` — that leaks across tenants; the existing `os.environ["GITHUB_TOKEN"]=` at workflows.py:1188 is a pre-existing multi-tenant leak, tracked separately). When `_fetch_github_token(tenant_id)` returns a token, inject an **ephemeral** git credential via `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` (process-scoped, no on-disk token, HOME-independent):
- `credential.https://github.com.helper` → `!f(){ echo username=x-access-token; echo "password=$GH_AUTH_TOKEN"; };f` (reads the token from a private env var; never written to a config file).
- `credential.interactive` → `never` (Codex).
- `GH_AUTH_TOKEN` set in the same `env` dict (the helper's only source).
Result: Claude's `git clone https://github.com/<repo-the-token-can-read>` authenticates as the user, HOME-correct, no disk persistence. (Shared helper `cli_runtime.build_git_credential_env()` so codex/gemini/copilot can adopt it next.)

### B. Fail-fast guards (Codex BLOCKER + IMPORTANT) — `Dockerfile` ENV + baked `/etc/gitconfig`
- `ENV GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false GCM_INTERACTIVE=never GIT_LFS_SKIP_SMUDGE=1`
- `ENV GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10"` **with GitHub host keys pre-baked** into `/etc/ssh/ssh_known_hosts` (Codex: avoid `accept-new` TOFU/MITM).
- Baked `/etc/gitconfig`: `http.lowSpeedLimit=1000` + `http.lowSpeedTime=30` (abort a stalled HTTPS clone, the gap `GIT_SSH_COMMAND` doesn't cover), `credential.interactive=never`.

### C. Stop the fake token — `entrypoint.sh` + `docker-compose.yml`
- entrypoint: run `gh auth login --with-token` and the startup self-clone **only** when `GITHUB_TOKEN` is non-empty AND `!= ghp_placeholder`.
- compose: `GITHUB_TOKEN=${GITHUB_TOKEN:-}` (empty default; Codex confirmed nothing requires it non-empty — chat dispatch overwrites when a tenant token exists, copilot re-fetches).

### D. No-drift mirror — `helm/values/agentprovision-code-worker.yaml` (+ `-local`)
Mirror the `GIT_*` env so K8s == compose.

## Out of scope (follow-ups)

- **Luna preflight UX** (Luna's ask): inject a "GitHub creds: connected/none" hint into the turn context so Luna says "I have no valid GitHub credentials — add a work-authorized token" and skips private-repo clone attempts (still allows public). Agent-prompt change — separate PR.
- **ustwo work-repo access:** depends on the *scope of the connected GitHub OAuth account*. If it doesn't cover ustwo, the user connects a ustwo-authorized GitHub account in `/integrations` (the registry supports multiple accounts + a `github_primary_account` pin). User action.
- **`os.environ["GITHUB_TOKEN"]=` multi-tenant leak** (workflows.py:1188) — pre-existing; fix to per-turn env separately.
- **Durable `.env` hydration** of `GITHUB_TOKEN` in the deploy.

## Verification (post-deploy, deployed image)

1. **No hang (the headline):** `alpha chat send "pull my work repos"` → completes **< 60s** with a clear auth/credentials error if the token can't reach them (not 1500s, not `exit -9`). `latency_ms` « 1.5e6.
2. **Authorized clone WORKS:** `alpha chat send "clone https://github.com/octocat/Hello-World and tell me the first line of its README"` → succeeds (public; proves the clone path runs end-to-end). If the connected token covers a private user repo, that clones too.
3. **Credential injection present:** the deployed image has the `GIT_*` ENV + baked gitconfig; a synthetic `git clone` of a private repo with no token → fails in seconds (not a prompt-hang).

## Process
plan (this) → Codex+Luna review (v1 done) → implement → Codex+Luna review of the diff → PR → merge (overnight/full-autonomy) → deploy → verify on deployed image → morning report.
