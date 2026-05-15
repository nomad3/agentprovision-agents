# Luna → Alpha Rebrand Plan

**Date:** 2026-05-14
**Status:** Draft, ready for review
**Owner:** @nomad3

## Summary

Unify the supervisor-agent persona, the Tauri desktop client, and the CLI under a
single product identity: **Alpha**. Today the platform exposes three nominally
separate surfaces that are conceptually the same thing — a user-facing AI
orchestrator:

- **Luna** — supervisor agent persona ("warm, WhatsApp-native co-pilot") + Tauri
  desktop client (`apps/luna-client`) + subdomain `luna.agentprovision.com`.
- **alpha** — terminal CLI (binary already named `alpha`, crates still
  `agentprovision-cli` / `agentprovision-core`).
- **The supervisor `Agent` row** — `Agent.name='Luna'` seeded per tenant by
  `apps/api/app/services/users.py`.

After this rebrand:

- One name across the CLI binary, the desktop app, and the supervisor agent —
  the same way "Claude" is both `claude` (CLI) and the agent you talk to, or
  "Gemini" is both `gemini` (CLI) and the agent.
- The platform / company / domain stays **agentprovision.com**. The umbrella
  GitHub repo stays `agentprovision-agents`. Internal infra names that aren't
  user-facing (Temporal queues `agentprovision-orchestration`,
  `agentprovision-code`; Helm chart prefix; DB name `agentprovision`) stay.

Scope explicitly includes a persona rewrite — Luna's "warm, short-message,
texting-style" voice is load-bearing on WhatsApp and is not a free 1:1 swap to
the more authoritative "Alpha" identity.

## Out of scope

- Renaming the platform / domain / org repo / Temporal queues / Postgres DB
  name. Those are infra identifiers, not product identity.
- Renaming `agentprovision-agents` itself.
- The Tauri-app capability extensions ("now that the CLI exists, drive the CLI
  from the desktop") — that work belongs in a follow-up PR series and should
  extend [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](2026-05-13-ap-cli-differentiation-roadmap.md),
  not be invented here. This plan only covers the rename.
- Changing macOS code-signing identity beyond what the new bundle ID requires.

## Naming model

| Surface | Before | After |
|---|---|---|
| Supervisor agent (`Agent.name`) | `Luna` | `Alpha` |
| Persona prompt (`users.py:173-177`) | "You are Luna, an intelligent AI co-pilot…" | Rewritten — see [Persona rewrite](#persona-rewrite). |
| WhatsApp persona | "warm, conversational, real human texting" | Adapted (see persona section). |
| Tauri product name (`tauri.conf.json`) | `Luna`, "Luna OS" | `Alpha`, "Alpha OS" |
| Tauri app directory | `apps/luna-client/` | `apps/alpha-client/` |
| Tauri bundle ID | `com.agentprovision.luna` | `com.agentprovision.alpha` |
| docker-compose service | `luna-client` | `alpha-client` |
| docker-compose env | `LUNA_PORT` | `ALPHA_PORT` (back-compat shim for one cycle) |
| Helm values file | `helm/values/agentprovision-luna-client-local.yaml` | `helm/values/agentprovision-alpha-client-local.yaml` |
| Cloudflared subdomain | `luna.agentprovision.com` | `alpha.agentprovision.com` (1:1 swap; old name kept as parallel route for one release, then removed) |
| GitHub Release tag prefix | `luna-vX.Y.Z` | `alpha-vX.Y.Z` |
| GitHub Actions workflow | `.github/workflows/luna-client-build.yaml` | `.github/workflows/alpha-client-build.yaml` |
| CLI binary | `alpha` | `alpha` (no change — already done) |
| CLI crate dir | `apps/agentprovision-cli/` | `apps/alpha-cli/` |
| CLI core crate dir | `apps/agentprovision-core/` | `apps/alpha-core/` |
| CLI keyring service | `"agentprovision"` | `"alpha"` (with one-shot read-shim that migrates the existing token) |
| CLI XDG path | `~/Library/Application Support/agentprovision/...` | `~/Library/Application Support/alpha/...` (with file-move shim on first run) |
| CLI env var | `AGENTPROVISION_TOKEN_FILE` | `ALPHA_TOKEN_FILE` (read both; deprecate old in two releases) |
| CLI env var | `AGENTPROVISION_SERVER` | `ALPHA_SERVER` (same shim) |
| Tauri storage key | `localStorage['luna_token']` | `localStorage['alpha_token']` (read shim copies on first load, then deletes) |
| Tauri DOM events | `luna-focus-chat`, `luna-agent-next`, `luna-dismiss`, `luna:logout`, etc. | `alpha-*` equivalents (dual-listen during shim period) |
| React components | `LunaAvatar`, `LunaCursor`, `LunaStateBadge`, `useLunaStream` | `AlphaAvatar`, `AlphaCursor`, `AlphaStateBadge`, `useAlphaStream` |
| Component dir | `apps/luna-client/src/components/luna/` | `apps/alpha-client/src/components/alpha/` |
| Console log prefix | `[Luna OS]`, `[Luna]` | `[Alpha OS]`, `[Alpha]` |
| Skill slug | `luna` | `alpha` |
| `local_inference.py` fn | `generate_luna_response_sync()` | `generate_alpha_response_sync()` |
| Migration filenames | `123_luna_meta_tool_group.sql`, `125_luna_prospecting_tool_groups.sql` | **Unchanged.** Migration history is immutable; renaming would break `_migrations` ordering. |

## Inventory (what we found)

`grep -ri 'luna' .` returns ~2,200 hits across the tree. Breakdown:

| Category | Count | Examples | Risk |
|---|---|---|---|
| Brand strings | ~50 | README.md, CLAUDE.md, AGENTS.md, CONTRIBUTING.md, GEMINI.md, `tauri.conf.json` (window titles, productName, tooltip), `users.py` persona prompt, default chat session title | Low |
| Identifiers | ~35 | `Agent.name='Luna'`, `skill_slug='luna'`, `luna_skills`, `generate_luna_response_sync`, `agent_router.py` Luna-name routing branch, migrations 123 & 125 `WHERE name='Luna'` | Medium (DB queries + agent routing) |
| Asset/binary names | ~20 | `apps/luna-client/`, docker-compose service `luna-client`, Helm values `agentprovision-luna-client-local.yaml`, `Luna.app`, `Luna_*.dmg`, `libluna_hand_landmarker.dylib` | Medium (cross-reference updates; cargo path edits) |
| External / public surface | ~30 | `kubernetes/cloudflared-deployment.yaml` (`luna.agentprovision.com`), GitHub Releases (`luna-vX.Y.Z` tag, `Luna_*.dmg` artifact, `latest.json` updater feed), macOS bundle ID `com.agentprovision.luna`, env var `LUNA_API_URL` | **High** (auto-updater chain + macOS code-signing identity + bookmarks) |

## PR breakdown

Five PRs, sequenced. PR N depends on PR N-1 having merged to `main`. Each PR is
chained off the previous branch (per the `feedback_chain_pr_branches.md` rule)
because every one of them touches the supervisor-agent identity in some form.

### PR 1 — `rebrand/alpha-strings-and-tauri-ui`

No infra change, no DB migration. Pure code/UI rename.

- All brand strings in `README.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`,
  `GEMINI.md`, `docs/` (excluding migration filenames and the changelog/history
  archives — those are dated records of what shipped under the old name and
  shouldn't be retconned).
- `apps/api/app/services/users.py`: persona prompt (rewritten — see
  [Persona rewrite](#persona-rewrite)), `Agent.name` literal, default chat
  session title, `skill_slug`, `luna_skills` → `alpha_skills`.
- `apps/api/app/services/local_inference.py`:
  `generate_luna_response_sync` → `generate_alpha_response_sync`. Update all
  callers in the same PR (chat service, free-tier fallback path).
- `apps/api/app/services/agent_router.py`: route on `Agent.name='Alpha'`. Keep
  `Luna` as a temporary fallback until PR 2's migration deploys, gated by a
  log line so we can verify the fallback stops firing in prod.
- `apps/api/app/services/whatsapp_service.py`: identity-change announcement
  message (sent once per chat session whose agent gets renamed by PR 2; see
  [WhatsApp continuity](#whatsapp-continuity)).
- Tauri JS (`apps/luna-client/src/`): rename `LunaAvatar` → `AlphaAvatar`,
  `LunaCursor` → `AlphaCursor`, `LunaStateBadge` → `AlphaStateBadge`,
  `useLunaStream` → `useAlphaStream`. Move `components/luna/` →
  `components/alpha/`. CSS classes `luna-*` → `alpha-*`. Console prefixes
  `[Luna OS]` → `[Alpha OS]`.
- Tauri storage + event shim (one-time, removed in PR 4):
  ```js
  // src/init/migrate-luna-state.js
  if (localStorage.getItem('luna_token') && !localStorage.getItem('alpha_token')) {
    localStorage.setItem('alpha_token', localStorage.getItem('luna_token'));
    localStorage.removeItem('luna_token');
  }
  // event listeners temporarily listen to both 'luna-*' and 'alpha-*'
  ```
- `tauri.conf.json`: window titles, `productName`, tray tooltip. **Bundle ID
  and updater endpoint NOT touched here** — that's PR 4.

### PR 2 — `rebrand/alpha-db-and-seeds` (off PR 1)

DB migration + seed-data rename.

- New migration `apps/api/migrations/129_rename_luna_to_alpha.sql`:
  ```sql
  -- Rename the supervisor agent per tenant
  UPDATE agents
     SET name = 'Alpha'
   WHERE name = 'Luna';
  -- Refresh chat session titles that reference the old name verbatim
  UPDATE chat_sessions
     SET title = REPLACE(title, 'Luna', 'Alpha')
   WHERE title LIKE '%Luna%';
  -- Skill slug rename in any existing integration_config rows
  UPDATE integration_config
     SET config = jsonb_set(config, '{skill_slug}', '"alpha"')
   WHERE config->>'skill_slug' = 'luna';
  ```
  (The `_migrations` row uses `filename`, not `name` — see
  [`feedback_migration_apply_pattern`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/migration_apply_pattern.md).)
- Updated seeders: `apps/api/scripts/seed_integral_tenant.py` and any other
  tenant seeder writing `name="Luna"` or `skill_slug="luna"`.
- Drop the `'Luna'` fallback in `agent_router.py` once this migration is
  confirmed applied in prod (i.e. the fallback log line stops firing for one
  full day).

Apply locally per the documented docker-compose pattern:

```bash
docker exec -i $(docker ps --format '{{.Names}}' | grep db-1) \
  psql -U postgres agentprovision \
  < apps/api/migrations/129_rename_luna_to_alpha.sql

docker exec -i $(docker ps --format '{{.Names}}' | grep db-1) \
  psql -U postgres agentprovision \
  -c "INSERT INTO _migrations (filename) VALUES ('129_rename_luna_to_alpha.sql');"
```

`*.sql` files need `git add -f` due to the global `.gitignore` rule.

### PR 3 — `rebrand/alpha-cli-crates` (off PR 2)

Rename the CLI crates and storage paths.

- `git mv apps/agentprovision-cli apps/alpha-cli`
- `git mv apps/agentprovision-core apps/alpha-core`
- `apps/alpha-cli/Cargo.toml`: `name = "alpha-cli"`. `default-run` already
  `alpha` — leave as-is.
- `apps/alpha-core/Cargo.toml`: `name = "alpha-core"`. `[lib] name =
  "alpha_core"`.
- Every `path = "../agentprovision-core"` → `path = "../alpha-core"`. Known
  consumers: `apps/alpha-cli/Cargo.toml`,
  `apps/luna-client/src-tauri/Cargo.toml` (this file is renamed in PR 4 but
  the dependency path needs flipping here so PR 3 leaves the workspace
  building).
- Workspace `Cargo.toml` `members = [...]`, `pnpm-workspace.yaml`,
  `package.json` workspaces — update paths.
- `apps/alpha-cli/src/context.rs`:
  ```rust
  const KEYRING_SERVICE: &str = "alpha";
  const LEGACY_KEYRING_SERVICE: &str = "agentprovision";
  // On first read: try "alpha", fall back to "agentprovision",
  // re-write under "alpha", delete the legacy entry, log success.
  ```
- XDG path: `$XDG_DATA_HOME/agentprovision/token` → `$XDG_DATA_HOME/alpha/token`.
  Same one-shot `if old.exists() && !new.exists() { fs::rename(old, new) }`
  shim. macOS equivalent path under `~/Library/Application Support/`
  follows the same pattern.
- Env vars: read `ALPHA_TOKEN_FILE` first, fall back to
  `AGENTPROVISION_TOKEN_FILE`. Same for `ALPHA_SERVER` /
  `AGENTPROVISION_SERVER`. Deprecation warning on stderr when the legacy var
  is the one consulted.
- `apps/alpha-cli/src/cli.rs` long_about and other docstrings: drop
  "AgentProvision command-line client", say "Alpha — AgentProvision's
  command-line client and AI orchestrator". Repo URL stays
  `https://github.com/nomad3/agentprovision-agents`.
- `apps/alpha-cli/src/commands/upgrade.rs`: keep `REPO_NAME =
  "agentprovision-agents"`. Auto-update fetches releases from the umbrella
  repo regardless of CLI rename.
- Internal logging targets: `agentprovision_cli={lvl},agentprovision_core=…`
  → `alpha_cli={lvl},alpha_core=…`.
- Crates.io: `alpha-cli` is **not** published to crates.io as of writing
  (verify via `cargo search`). If unpublished, just publish under the new
  name. If it has been published, ship a transitional `agentprovision-cli`
  v0.8.0 that depends on `alpha-cli` and renames its binary to `alpha`,
  to keep `cargo install agentprovision-cli` working for one cycle.

### PR 4 — `rebrand/alpha-tauri-bundle-and-infra` (off PR 3)

The high-blast PR. Bundle ID, updater feed, subdomain, docker-compose, Helm.

- `git mv apps/luna-client apps/alpha-client`. Update internal package.json
  `"name"`, Vite config, Tauri Rust crate name in
  `src-tauri/Cargo.toml` (`luna-client` → `alpha-client`).
- `apps/alpha-client/src-tauri/tauri.conf.json`:
  - `productName: "Alpha"`
  - `identifier: "com.agentprovision.alpha"`
  - Updater endpoint URL flipped from the old `latest.json` location to the
    new Alpha-branded one. Both feeds live in parallel for one release cycle
    so the final transitional `luna-vX.Y.Z` build (see below) can point its
    auto-updater at the new endpoint.
  - `bundle.macOS.frameworks`: rename `libluna_hand_landmarker.dylib` →
    `libalpha_hand_landmarker.dylib` and update the build.rs that mirrors it
    into `target/lib/` (per
    [`feedback_luna_tauri_dylib_bundling`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/luna_tauri_dylib_bundling.md)
    — the dylib must be both copied into `target/lib/` *and* listed in the
    bundle config or the app crashes at launch).
- **Final transitional Luna release.** Before merging the bundle-ID change,
  ship one last `luna-vX.Y.Z` build whose `latest.json` points at the
  upcoming Alpha bundle. Existing installs get one auto-update notification
  ("Alpha is here — download from agentprovision.com/download to keep your
  desktop client working"). The bundle-ID change still requires a fresh
  install on macOS — the old code-signing identity can't auto-update across
  bundle-ID boundaries. This is documented in the in-app banner copy and in
  the release notes.
- `docker-compose.yml`: service `luna-client` → `alpha-client`. Env
  `LUNA_PORT` → `ALPHA_PORT` with a dual-read shim:
  ```yaml
  ports:
    - "${ALPHA_PORT:-${LUNA_PORT:-8009}}:80"
  ```
  Removed in the PR-after-this-one (call it PR 6 if it ever ships) once
  every dev's `.env` has been updated.
- Helm: `git mv helm/values/agentprovision-luna-client-local.yaml
  helm/values/agentprovision-alpha-client-local.yaml`. Update `nameOverride`,
  `fullnameOverride`, `repository` to `agentprovision-alpha-client`.
- `kubernetes/cloudflared-deployment.yaml`: add a parallel route for
  `alpha.agentprovision.com` pointing at the same backend. Keep the
  `luna.agentprovision.com` route for one release cycle (it 200s and serves
  the same UI), then remove. Coordinate the DNS cutover with whoever owns
  the cloudflared tunnel config.
- `.github/workflows/luna-client-build.yaml` → `alpha-client-build.yaml`.
  Tag prefix `luna-v*` → `alpha-v*`. Update the workflow's branches trigger,
  artifact names, release title format. Repo secrets `LUNA_API_URL` →
  `ALPHA_API_URL` (rotate via repo settings; keep both populated for one
  build cycle).
- Update the per-user CLAUDE.md / global rule about
  "we use kubernetes cluster with kubeconfig on the local machine" — N/A
  here, that's a separate rule about tenant work, not this rebrand.

### PR 5 — `rebrand/alpha-cleanup` (off PR 4, deferred ≥1 release)

Removes the back-compat shims after one release cycle confirms no fallback
firings.

- Delete the `Luna` fallback branch in `agent_router.py` (already done in
  PR 2 if the fallback log went silent).
- Delete the localStorage / event-name dual-listen in Tauri.
- Delete the legacy keyring / XDG / env-var read paths from the CLI.
- Delete the `luna.agentprovision.com` cloudflared route.
- Delete the `LUNA_PORT` / `LUNA_API_URL` shims from docker-compose and
  GitHub Actions.
- Final pass through the codebase: any `// luna` / `# luna` /
  `<!-- luna -->` reference comments left behind by the rename PRs.

## Persona rewrite

Today the supervisor's persona prompt (`apps/api/app/services/users.py:173-177`)
sets a specific voice: "warm, conversational, sends short messages like real
human texting". That voice is tuned for the WhatsApp channel — long-form chat
clients (web, Tauri) inherit it but tolerate it; WhatsApp depends on it.

`Alpha` as a name suggests a more authoritative orchestrator persona. We have
two reasonable shapes:

**Option A — keep the warm voice, just rename.** Lowest risk on WhatsApp UX.
Risk: "Alpha" + warm-texting voice reads slightly off-brand for an orchestrator
identity. Doable but feels like a half-rebrand.

**Option B — split the persona along channels.** New `Alpha` base persona
(authoritative orchestrator: routes, decides, hands off) with a per-channel
overlay that softens for WhatsApp ("brief, conversational, mobile-friendly")
and stays formal for web / Tauri / CLI. The overlay system already exists in
the agent prompt-assembly path (`memory_domains`, `persona_prompt`,
`tool_groups`).

**Recommended: Option B.** Concretely:

- Base prompt (`agents.persona_prompt`):
  > You are Alpha, the orchestrator agent for this tenant. You route work to
  > the right specialist agent (Code, Sales, Data, Marketing, Personal
  > Assistant), or you handle it yourself when it doesn't need delegation.
  > You remember context across sessions via the memory layer pre-loaded into
  > your CLAUDE.md. You explain your reasoning when it matters, stay concise
  > when it doesn't, and always tell the user which agent / CLI runtime
  > actually did the work.

- WhatsApp channel overlay (added by `whatsapp_service.py` when assembling the
  per-turn prompt):
  > Reply in 1-3 short messages, like texting. Skip headers and bullet lists
  > unless the user asks for structure. If the answer is long, offer to send
  > the full version to the web client.

- Tauri / web / CLI: no overlay, base prompt only.

This matches how the platform already differentiates channel UX (typing
indicators, MediaRecorder paths, Spatial HUD) — the persona just gets the same
treatment.

## WhatsApp continuity

Existing WhatsApp threads have history where the bot signs as Luna. When PR 2
flips the agent name, we send one identity-change announcement per active
WhatsApp chat session, gated on `last_active_at > now() - interval '30 days'`:

> Heads up: I'm now called **Alpha** — same agent, same memory of our
> conversations, just a new name as we roll out the unified orchestrator
> across the desktop app and the CLI. You can keep messaging me here as
> normal.

Implementation: a one-shot Temporal activity triggered by the migration script
(or run manually after PR 2 deploys), iterating over recent active chats and
sending the message via `WhatsAppService.send_message()`. Idempotent — gated
on a `chat_session.metadata.alpha_announcement_sent_at` flag.

## Backwards compatibility summary

| Surface | Shim | Removed in |
|---|---|---|
| `Agent.name='Luna'` | `agent_router.py` falls back to `'Luna'` lookups | PR 2 → PR 5 |
| `localStorage['luna_token']` | First-load migration to `alpha_token` | PR 1 → PR 5 |
| Tauri DOM events `luna-*` | Dual-listen on `luna-*` + `alpha-*` | PR 1 → PR 5 |
| Keyring service `"agentprovision"` | First-read fallback + auto-migrate | PR 3 → PR 5 |
| XDG / Application Support path | First-run file move | PR 3 → PR 5 |
| Env vars `AGENTPROVISION_*` | Read both, deprecation warning on legacy | PR 3 → PR 5 |
| `LUNA_PORT` / `LUNA_API_URL` | docker-compose + GH Actions dual-read | PR 4 → PR 5 |
| `luna.agentprovision.com` | Parallel cloudflared route to same backend | PR 4 → PR 5 |
| `latest.json` updater feed | Final `luna-vX.Y.Z` release points at Alpha bundle | PR 4 (one-shot) |
| Bundle ID `com.agentprovision.luna` | **No shim possible** — macOS code signing forces fresh install | PR 4 (breaking) |

## Rollback story

| PR | Rollback |
|---|---|
| 1 | `git revert`. No state change. |
| 2 | Run inverse migration: `UPDATE agents SET name='Luna' WHERE name='Alpha'`; `UPDATE chat_sessions SET title=REPLACE(title,'Alpha','Luna') WHERE title LIKE '%Alpha%'`. Restore `agent_router.py` Luna-first lookup. Pause the WhatsApp announcement script if it hasn't completed. |
| 3 | `git revert`. CLI users on the new build keep working because the dual-read shim still finds their token under either keyring service / either XDG path. |
| 4 | Re-point cloudflared at the old route. Re-add `luna.*` GitHub Actions workflow. Bundle-ID change cannot be reverted cleanly — users who installed the new app keep the new bundle; downgrading means a fresh install of the old bundle. Document this as a one-way door. |
| 5 | Cleanup-only PR. Reverting just restores the shims; nothing user-visible changes. |

## Verification checklist

Run after each PR. Per
[`feedback_verification_function`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/feedback_verification_function.md)
— evidence before assertions, every stage.

After PR 1:
- [ ] `grep -r 'Luna' apps/web apps/api apps/luna-client docs README.md CLAUDE.md AGENTS.md` returns only intentional residual hits (changelog/migration filenames; document them in the PR description)
- [ ] `pytest apps/api/tests` green
- [ ] Tauri dev mode launches, window title says "Alpha", tray tooltip says "Alpha"
- [ ] Browser dev console logs show `[Alpha OS]` prefix
- [ ] Existing user with `luna_token` in localStorage stays logged in (shim worked)
- [ ] `agent_router.py` fallback log line fires exactly once on first chat from an un-migrated tenant

After PR 2:
- [ ] `psql -c "SELECT count(*) FROM agents WHERE name = 'Luna';"` returns `0`
- [ ] `psql -c "SELECT count(*) FROM agents WHERE name = 'Alpha';"` returns the expected per-tenant count
- [ ] No new fallback log lines from `agent_router.py` for 24h
- [ ] WhatsApp announcement message delivered to all chat sessions with `last_active_at > now() - interval '30 days'`; `alpha_announcement_sent_at` flag set on each
- [ ] `_migrations` table has the `129_rename_luna_to_alpha.sql` row

After PR 3:
- [ ] `cargo build --workspace` clean
- [ ] `cargo test --workspace` clean
- [ ] Existing CLI install: `alpha status` reports authenticated without re-login (keyring shim worked)
- [ ] Fresh CLI install: token lands under `"alpha"` keyring service / `~/Library/Application Support/alpha/`
- [ ] Both `ALPHA_TOKEN_FILE=… alpha status` and `AGENTPROVISION_TOKEN_FILE=… alpha status` work; the latter prints the deprecation warning

After PR 4:
- [ ] `docker compose up -d --force-recreate alpha-client` brings up the desktop service on port `${ALPHA_PORT:-8009}`
- [ ] `https://alpha.agentprovision.com` returns 200 and serves the desktop client
- [ ] `https://luna.agentprovision.com` still returns 200 (parallel route)
- [ ] Existing macOS Luna install receives the final `luna-vX.Y.Z` update notification with the cutover banner copy
- [ ] Fresh install of `Alpha.app` writes its bundle to `com.agentprovision.alpha` (verify with `defaults read com.agentprovision.alpha`)

After PR 5:
- [ ] `grep -r 'Luna\|luna' apps/ helm/ kubernetes/ docker-compose.yml docs/` returns only intentional residuals (migration filenames; archived changelog; this rebrand plan itself)
- [ ] cloudflared route for `luna.*` removed; `https://luna.agentprovision.com` returns NXDOMAIN or a 404 from cloudflare
- [ ] `LUNA_PORT` / `LUNA_API_URL` removed from docker-compose, GH Actions secrets, dev `.env` examples
- [ ] No new error log lines from missing legacy paths

## Risks

- **Bundle-ID change forces reinstall.** No mitigation — macOS code-signing
  invariant. Mitigated by the in-app announcement banner shipped in the final
  Luna release.
- **WhatsApp announcement spam.** Mitigated by 30-day-active gate +
  per-session idempotency flag.
- **Migration runs while a chat is in flight.** Acceptable — `Agent.name` is
  read on session bind, not per-turn; an in-flight session keeps the rename
  invisible until the next message.
- **Drift between docker-compose (current ground truth) and Helm/K8s
  (aspirational per CLAUDE.md).** Per the user's
  [`feedback_no_local_builds`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/feedback_no_local_builds.md)
  rule and the documented helm-and-git-and-terraform sync rule, all four
  surfaces (compose, Helm, GH Actions, terraform if applicable) get the
  rename in PR 4 even though only compose is the active runtime today.

## Follow-ups (out of scope here)

- The "extend the Tauri app now that the CLI exists" capability work — Tauri
  panel showing live `alpha` CLI sessions, `/cli <task>` shortcut in chat
  that dispatches via the CLI control plane, HUD nebula leaves orbiting an
  Alpha core. This is a follow-up PR series rooted in
  [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](2026-05-13-ap-cli-differentiation-roadmap.md),
  not in this rebrand.
- Documentation pass on `docs/changelog/*.md` — leave historical entries
  describing "Luna" untouched (they're dated records of what shipped under
  the old name); only flip prose in present-tense reference docs.
- A `docs/cli/README.md` refresh once the crate paths in PR 3 land — the
  current "Sources live under `apps/agentprovision-cli` and
  `apps/agentprovision-core`" line stops being true after PR 3.
