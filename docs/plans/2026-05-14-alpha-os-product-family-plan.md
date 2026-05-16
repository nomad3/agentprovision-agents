# Alpha OS — Product Family Plan

**Date:** 2026-05-14 (supersedes the early-draft "Luna → Alpha rebrand" framing in PR #478)
**Status:** Draft, ready for review
**Owner:** @nomad3

## TL;DR

agentprovision ships a **two-product family**, not a single brand. This plan
gives the family explicit names, renames the desktop / CLI shell from "Luna" to
"Alpha OS", and leaves the supervisor agent persona untouched as "Luna".

| Layer | Name | What it is |
|---|---|---|
| Platform / company / domain | **agentprovision** | `agentprovision.com`, `agentprovision-agents` umbrella repo, Temporal queues, Postgres DB, internal infra |
| OS surface (the thing you install + run) | **Alpha** | Tauri desktop app, `alpha` CLI binary, spatial workstation HUD ("Alpha OS"), bundle ID, subdomain, auto-updater, global shortcuts, tray, OS-shell UX |
| AI supervisor / persona (the one you talk to) | **Luna** | `Agent.name='Luna'` seeded per tenant, WhatsApp persona, `LunaAvatar`, Luna's skill bundle, free-tier fallback persona |

Pattern reference: **Apple → macOS + Siri**, **Google → Android + Assistant**,
**Microsoft → Windows + Cortana**. *Not* Anthropic → Claude (where the tool and
the persona share a name).

This plan only renames the **OS surface**. Luna stays Luna. No DB migration on
the supervisor name. No persona prompt rewrite. No WhatsApp identity-change
announcement. Those were in the prior draft of this plan; they're gone.

## Why this framing matters

The platform has been quietly carrying two distinct things under one name:
- "Luna" the supervisor agent — a persona seeded per tenant, with a warm
  WhatsApp-native voice, that routes work across specialist agents.
- "Luna" the Tauri client / spatial HUD / desktop product — the shell you
  install on macOS, the menu-bar presence, the auto-updater, the bundle ID.

These are different products. They've been entangled in docs, code, and infra
because they shipped together and shared a name. The entanglement is now
actively costly:
- The CLI (`alpha` binary) ships outside this naming and has to be explained
  every time as "the terminal counterpart to Luna" — when really it's the
  CLI face of the same OS surface the Tauri app is the desktop face of.
- New surfaces (web cockpit at `/den`, the Alpha Control Plane) have started
  picking up "Alpha" organically because it fits — but without the family
  being named, every doc has to relitigate which is which.
- Persona evolution (Luna's voice, memory, emotional state machine) and OS
  evolution (auto-updater, global shortcuts, spatial HUD) have completely
  different roadmaps, owners, and risk profiles. One name for both prevents
  clean planning.

Naming the family fixes all three.

## Naming model (authoritative)

### agentprovision — the platform

Everything that's about the company, the multi-tenant SaaS, the domain, the
codebase as a whole. **No rename. No new surface.** Specifically stays as
`agentprovision`:
- Domain: `agentprovision.com`
- Umbrella GitHub repo: `agentprovision-agents`
- Postgres database name: `agentprovision`
- Temporal queues: `agentprovision-orchestration`, `agentprovision-code`,
  `agentprovision-business`
- Helm chart prefix where it represents the platform (`agentprovision-api`,
  `agentprovision-web`, etc.)
- Helm release name
- All internal infra names that aren't user-facing

### Alpha — the OS surface

Everything that's about the thing the user installs and runs to interact with
the platform. **Renamed from "Luna" (where it's currently entangled).**

| Surface | Before | After |
|---|---|---|
| Tauri product name (`tauri.conf.json:productName`) | `Luna` | `Alpha` |
| Tauri main-window title | `Luna` | `Alpha` |
| Tauri spatial-HUD window title | `Luna OS` | `Alpha OS` |
| Tauri tray tooltip | `Luna — AI Assistant` | `Alpha — agentprovision OS` |
| Tauri app directory | `apps/luna-client/` | `apps/alpha-client/` |
| Tauri Rust crate (`src-tauri/Cargo.toml:name`) | `luna-client` | `alpha-client` |
| Tauri bundle ID | `com.agentprovision.luna` | `com.agentprovision.alpha` |
| Tauri dylib bundled by build.rs | `libluna_hand_landmarker.dylib` | `libalpha_hand_landmarker.dylib` |
| docker-compose service | `luna-client` | `alpha-client` |
| docker-compose env | `LUNA_PORT` | `ALPHA_PORT` (back-compat shim for one cycle) |
| Helm values file | `helm/values/agentprovision-luna-client-local.yaml` | `helm/values/agentprovision-alpha-client-local.yaml` |
| Cloudflared subdomain | `luna.agentprovision.com` | `alpha.agentprovision.com` (1:1 swap; old name kept as parallel route for one release, then removed) |
| GitHub Release tag prefix | `luna-vX.Y.Z` | `alpha-vX.Y.Z` |
| GitHub Actions workflow | `.github/workflows/luna-client-build.yaml` | `.github/workflows/alpha-client-build.yaml` |
| GitHub Actions secret | `LUNA_API_URL` | `ALPHA_API_URL` (rotate; keep both populated for one cycle) |
| CLI binary | `alpha` | `alpha` (no change — already done) |
| CLI crate dir | `apps/agentprovision-cli/` | `apps/alpha-cli/` |
| CLI core crate dir | `apps/agentprovision-core/` | `apps/alpha-core/` |
| CLI crate name | `agentprovision-cli` | `alpha-cli` |
| CLI core crate name | `agentprovision-core` | `alpha-core` |
| CLI lib name | `agentprovision_core` | `alpha_core` |
| CLI keyring service | `"agentprovision"` | `"alpha"` (with first-read fallback + auto-migrate) |
| CLI XDG / Application Support path | `agentprovision/` | `alpha/` (with first-run file move) |
| CLI env vars | `AGENTPROVISION_TOKEN_FILE`, `AGENTPROVISION_SERVER` | `ALPHA_TOKEN_FILE`, `ALPHA_SERVER` (read both; deprecation warning on legacy) |
| Tauri storage key | `localStorage['luna_token']` | `localStorage['alpha_token']` (one-shot migration on first load) |
| Tauri DOM events (app-shell, not persona) | `luna-focus-chat`, `luna-agent-next`, `luna-dismiss`, `luna:logout` | `alpha-*` equivalents (dual-listen during shim period) |
| App-shell CSS classes (chrome, not avatar) | `luna-app`, `luna-nav`, `luna-brand`, `luna-btn` | `alpha-app`, `alpha-nav`, `alpha-brand`, `alpha-btn` |
| Console log prefix (OS-level) | `[Luna OS]` | `[Alpha OS]` |

### Luna — the supervisor persona

Everything that's about the AI agent — the persona, the voice, the avatar,
the skills attached to her. **Stays Luna.** No code change.

| Surface | Stays as |
|---|---|
| Agent row | `Agent.name='Luna'` |
| Persona prompt (`users.py:173-177`) | "You are Luna, an intelligent AI co-pilot…" |
| WhatsApp identity / typing indicator persona | Luna — warm, conversational, short-message |
| Free-tier fallback function | `generate_luna_response_sync()` |
| Skills bundle | `luna_skills = ["luna"]`, `skill_slug='luna'` |
| Avatar component (renders Luna's face) | `LunaAvatar`, `LunaAvatar.css`, `LunaCursor`, `LunaStateBadge` |
| Avatar streaming hook | `useLunaStream` |
| Avatar component directory | `apps/.../src/components/luna/` (path moves to under `alpha-client/src/...` per the dir rename, but the inner `luna/` folder name stays — it holds the Luna-persona renderers) |
| `[Luna]` log prefix (persona events, distinct from `[Luna OS]`) | Stays `[Luna]` |
| WhatsApp service Luna identity | No change |
| Default chat session title ("Chat with Luna") | Stays |
| `agent_router.py` Luna name lookup | Stays |
| Migration files referencing `WHERE name='Luna'` (123, 125) | Stays (and remain correct because the agent name doesn't change) |
| Luna Memory System docs section | Stays (it's about Luna the persona, who has memory) |
| Luna Presence System docs section | Stays (Luna's emotional state machine) |

Crucially: there is **no DB migration** in this plan. No
`UPDATE agents SET name='Alpha'`. Luna remains the supervisor's name.

### Migration filenames

Migration filenames are immutable history; the existing
`123_luna_meta_tool_group.sql` and `125_luna_prospecting_tool_groups.sql` stay
as-is. They're about Luna's tool groups (the supervisor's skill bundle), which
is conceptually correct under this model anyway.

## Inventory delta vs. the original draft

The earlier draft of this plan estimated ~2,200 "Luna" occurrences and planned
to flip almost all of them. Under the corrected model the rename is much
narrower:

| Category | Original draft | This plan |
|---|---|---|
| Brand strings (docs, UI) | ~50 — all flipped | ~30 — flipped only where they refer to the desktop OS or "Luna OS" the HUD. References to Luna-the-persona stay. |
| Identifiers | ~35 — all flipped, plus DB migration | ~12 — only CLI crate names, keyring/XDG, env vars, Tauri storage keys, app-shell CSS, `[Luna OS]` prefix. `Agent.name`, persona prompt, `LunaAvatar`, `luna_skills`, `generate_luna_response_sync`: all stay. |
| Asset / binary names | ~20 — all flipped | ~20 — same (these are OS-surface: Tauri app dir, bundle, dylib, docker service, Helm values, workflow file) |
| External / public surface | ~30 — all flipped | ~20 — subdomain, releases, bundle ID, env secrets. Cloudflared `luna.*` route kept for one release as parallel alias. |
| **Removed sections entirely** | — | DB migration (PR 2 in prior draft), persona rewrite section, WhatsApp identity-change announcement |

## PR breakdown

Four PRs, chained off each other per the `feedback_chain_pr_branches` rule.
Four, not five — the prior draft's PR 2 (DB migration) is gone because the
supervisor agent's name doesn't change.

### PR 1 — `rebrand/alpha-os-strings-and-app-shell`

Pure code/UI rename. No infra, no DB, no breaking changes.

- Doc-level brand strings flipped only where they describe the desktop /
  spatial / CLI as a product:
  - README.md "Luna — Native AI Client" section → "Alpha — agentprovision's
    Native OS" (recast to match the family model; explicitly name Luna as
    the persona that runs inside Alpha).
  - README.md "Luna OS Spatial Workstation" → "Alpha OS — Spatial
    Workstation".
  - README.md "Luna OS Roadmap" → "Alpha OS Roadmap".
  - README.md "Luna Memory System" / "Luna Presence System" → **unchanged**
    (these are about Luna the persona).
  - README.md architecture diagram caption "Luna desktop (Tauri 2.0)" →
    "Alpha desktop (Tauri 2.0)".
  - README.md install / quickstart references to `luna.agentprovision.com`
    → `alpha.agentprovision.com`.
  - CLAUDE.md "Luna Native Client" section → "Alpha Native Client".
  - CLAUDE.md "Luna OS Spatial Workstation" section → "Alpha OS Spatial
    Workstation".
  - CLAUDE.md reference to `apps/luna-client` → `apps/alpha-client` (path
    rename lands in PR 3).
  - AGENTS.md, CONTRIBUTING.md, GEMINI.md: same selective treatment —
    rename product/install/path references, keep persona references.
  - Add a new short top-of-README "Product family" section establishing
    the three names (agentprovision / Alpha / Luna) so newcomers don't
    re-conflate them.
- Tauri JS app-shell renames in `apps/luna-client/src/`:
  - CSS classes for app chrome: `luna-app` → `alpha-app`, `luna-nav` →
    `alpha-nav`, `luna-brand` → `alpha-brand`, `luna-btn` → `alpha-btn`,
    `luna-btn-sm` → `alpha-btn-sm`.
  - Console prefixes: `console.log('[Luna OS] ...')` → `'[Alpha OS] ...'`.
    `console.error('[Luna OS] ...')` → `'[Alpha OS] ...'`. The single
    `console.error('[Luna] install_update failed...')` becomes `[Alpha OS]`
    too because install/update is OS-level, not persona.
  - Storage keys: one-shot migration shim copies `luna_token` →
    `alpha_token`, `luna_theme` → `alpha_theme`, then deletes the
    originals. Reads check the new key first.
  - DOM events: dual-listen on `luna-focus-chat` + `alpha-focus-chat`,
    same for `luna-agent-next`, `luna-agent-prev`, `luna-dismiss`,
    `luna-memory-record`, `luna-session-change`, `luna:logout`. Dispatch
    new names. Old listeners removed in PR 4.
  - **Do NOT rename** `LunaAvatar.jsx`, `LunaAvatar.css`, `LunaCursor.jsx`,
    `LunaStateBadge.jsx`, `useLunaStream.js`, `LunaAvatar.test.jsx`,
    `LunaStateBadge.test.jsx`, or the `components/luna/` directory. These
    render Luna the persona.
- `tauri.conf.json`:
  - `productName: "Alpha"` (was `"Luna"`)
  - Spatial-HUD window title `"Alpha OS"` (was `"Luna OS"`)
  - Main window title `"Alpha"` (was `"Luna"`)
  - Tray tooltip `"Alpha — agentprovision OS"` (was `"Luna — AI Assistant"`)
  - **Bundle ID + updater endpoint NOT touched here.** Deferred to PR 3.
- `agent_router.py`, `users.py`, `local_inference.py`, `whatsapp_service.py`,
  WhatsApp typing-indicator persona, persona prompts: **no changes**. Luna
  stays.

### PR 2 — `rebrand/alpha-os-cli-crates-and-paths` (off PR 1)

Rename the CLI crates and the on-disk state owned by the CLI. The CLI binary
name is already `alpha`; this is the rest of the move.

- `git mv apps/agentprovision-cli apps/alpha-cli`
- `git mv apps/agentprovision-core apps/alpha-core`
- `apps/alpha-cli/Cargo.toml`: `name = "alpha-cli"`. `default-run = "alpha"`
  unchanged. `description` updated to "The Alpha CLI — terminal surface of
  agentprovision's Alpha OS. Login, chat with Luna, run workflows."
- `apps/alpha-core/Cargo.toml`: `name = "alpha-core"`. `[lib] name = "alpha_core"`.
  `description` updated.
- Every `path = "../agentprovision-core"` flipped to `path = "../alpha-core"`.
  Known consumers:
  - `apps/alpha-cli/Cargo.toml`
  - `apps/luna-client/src-tauri/Cargo.toml` (the dir rename of luna-client →
    alpha-client lands in PR 3; the import path flip lands here so the
    workspace keeps building).
- Workspace `Cargo.toml`, `pnpm-workspace.yaml`, `package.json` workspaces —
  update member paths.
- `apps/alpha-cli/src/context.rs`:
  ```rust
  const KEYRING_SERVICE: &str = "alpha";
  const LEGACY_KEYRING_SERVICE: &str = "agentprovision";
  // First read: try "alpha", fall back to "agentprovision",
  // re-write under "alpha", delete the legacy entry, log success once.
  ```
- XDG / `Application Support` path: `~/Library/Application Support/agentprovision/`
  → `~/Library/Application Support/alpha/`. Same one-shot
  `if old_dir.exists() && !new_dir.exists() { fs::rename(old_dir, new_dir) }`
  shim on first run. Equivalent XDG path on Linux.
- Env vars: read `ALPHA_TOKEN_FILE` first, fall back to
  `AGENTPROVISION_TOKEN_FILE`. Same for `ALPHA_SERVER` /
  `AGENTPROVISION_SERVER`. One-line deprecation warning on stderr when the
  legacy var is the one consulted.
- `apps/alpha-cli/src/cli.rs` `long_about` docstring: "Alpha — the CLI
  surface of agentprovision's Alpha OS. Login, chat with Luna, run
  workflows, and orchestrate agents from your terminal."
- `apps/alpha-cli/src/commands/upgrade.rs`: keep `REPO_NAME =
  "agentprovision-agents"` (umbrella repo doesn't rename; auto-update
  fetches Alpha releases from there).
- Internal `RUST_LOG` targets:
  `agentprovision_cli={lvl},agentprovision_core=…` →
  `alpha_cli={lvl},alpha_core=…`.
- Crates.io: verify whether `agentprovision-cli` was ever published
  (`cargo search agentprovision-cli`). If yes, ship a transitional
  `agentprovision-cli` v0.8 that depends on `alpha-cli` and re-exports the
  `alpha` binary; if not, just publish under the new name.
- `docs/cli/README.md`: replace the line "Sources live under
  `apps/agentprovision-cli` and `apps/agentprovision-core`" with the new
  paths, and add a one-sentence "The CLI is the terminal surface of Alpha
  OS; the agent you chat with is Luna" so the family model is on the
  reference doc.

### PR 3 — `rebrand/alpha-os-tauri-dir-and-bundle` (off PR 2)

Tauri app dir rename + bundle ID + updater + Helm + cloudflared. The
high-blast PR.

- `git mv apps/luna-client apps/alpha-client`
- Update internal references: `apps/alpha-client/package.json` `"name"`,
  Vite config, Tauri Rust crate name in `src-tauri/Cargo.toml`
  (`luna-client` → `alpha-client`). Inner `src/components/luna/` directory
  stays (renders Luna).
- `apps/alpha-client/src-tauri/tauri.conf.json`:
  - `identifier: "com.agentprovision.alpha"` (was `"com.agentprovision.luna"`)
  - Updater endpoint URL flipped to the new Alpha `latest.json` location.
    Both feeds live in parallel for one release cycle so the final
    transitional `luna-vX.Y.Z` release (see below) can point its
    auto-updater at the new endpoint.
  - `bundle.macOS.frameworks`: rename `libluna_hand_landmarker.dylib` →
    `libalpha_hand_landmarker.dylib` and update the `build.rs` that mirrors
    the dylib into `target/lib/` (per
    [`luna_tauri_dylib_bundling`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/luna_tauri_dylib_bundling.md)
    — must be copied into `target/lib/` *and* listed in the bundle config
    or the app crashes at launch).
- **Final transitional Luna release.** Before merging the bundle-ID change,
  ship one last `luna-vX.Y.Z` build whose `latest.json` points at the
  upcoming Alpha bundle. Existing installs get one auto-update notification
  with banner copy along the lines of:

  > **You're getting an upgrade.** Luna is now called Alpha — the
  > desktop / CLI / spatial workstation. Luna is still here as your
  > supervisor agent inside Alpha. Because the macOS bundle identity
  > changes (`com.agentprovision.luna` → `com.agentprovision.alpha`),
  > the auto-updater can't carry you over — please download Alpha from
  > agentprovision.com/download. Your tenant, your memory, and Luna
  > herself are unchanged.

  The bundle-ID change requires a fresh install on macOS; the in-app
  banner and release notes carry that message.
- `docker-compose.yml`: service `luna-client` → `alpha-client`. Env:
  ```yaml
  ports:
    - "${ALPHA_PORT:-${LUNA_PORT:-8009}}:80"
  ```
  Dual-read shim removed in PR 4.
- Helm: `git mv helm/values/agentprovision-luna-client-local.yaml
  helm/values/agentprovision-alpha-client-local.yaml`. Update
  `nameOverride`, `fullnameOverride`, `repository` to
  `agentprovision-alpha-client`. (Currently aspirational per CLAUDE.md;
  docker-compose is the active runtime, but we keep Helm in sync per the
  no-drift rule.)
- `kubernetes/cloudflared-deployment.yaml`: add a parallel route for
  `alpha.agentprovision.com` pointing at the same backend. Keep the
  `luna.agentprovision.com` route for one release cycle (it 200s and
  serves the same UI). Removed in PR 4.
- `.github/workflows/luna-client-build.yaml` → `alpha-client-build.yaml`.
  Tag prefix `luna-v*` → `alpha-v*`. Update branches trigger, artifact
  names, release title format. Repo secret `LUNA_API_URL` → `ALPHA_API_URL`
  (rotate via repo settings; keep both populated for one build cycle).

### PR 4 — `rebrand/alpha-os-cleanup` (off PR 3, deferred ≥1 release)

Removes the back-compat shims after one release cycle confirms no fallback
firings.

- Tauri: delete the `luna_token` / `luna_theme` localStorage read shim and
  the dual-listen on `luna-*` DOM events.
- CLI: delete the `"agentprovision"` keyring read fallback, the
  `Application Support/agentprovision/` directory move fallback, and the
  `AGENTPROVISION_*` env var read fallbacks. Tokens not migrated by then
  are stranded — accept; users can `alpha login` again.
- Infra: delete the `luna.agentprovision.com` cloudflared route. Delete
  the `LUNA_PORT` / `LUNA_API_URL` shims from docker-compose and GH
  Actions secrets.
- Final pass: any `// luna` / `# luna` / `<!-- luna -->` reference
  comments left behind by the rename PRs that referred to *OS-shell*
  concerns. Persona comments stay.

## Backwards compatibility summary

| Surface | Shim | Removed in |
|---|---|---|
| `localStorage['luna_token']` | First-load migration to `alpha_token` | PR 1 → PR 4 |
| `localStorage['luna_theme']` | First-load migration to `alpha_theme` | PR 1 → PR 4 |
| Tauri DOM events `luna-*` | Dual-listen on `luna-*` + `alpha-*` | PR 1 → PR 4 |
| Keyring service `"agentprovision"` | First-read fallback + auto-migrate | PR 2 → PR 4 |
| XDG / Application Support path | First-run directory move | PR 2 → PR 4 |
| Env vars `AGENTPROVISION_*` | Read both, deprecation warning on legacy | PR 2 → PR 4 |
| `LUNA_PORT` / `LUNA_API_URL` | docker-compose + GH Actions dual-read | PR 3 → PR 4 |
| `luna.agentprovision.com` | Parallel cloudflared route to same backend | PR 3 → PR 4 |
| `latest.json` updater feed | Final `luna-vX.Y.Z` release points at Alpha bundle | PR 3 (one-shot) |
| Bundle ID `com.agentprovision.luna` | **No shim possible** — macOS code-signing forces fresh install | PR 3 (breaking) |

## Rollback story

| PR | Rollback |
|---|---|
| 1 | `git revert`. No state change. localStorage shim is self-healing in either direction. |
| 2 | `git revert`. Existing CLI installs keep working because the dual-read shim still finds tokens under either keyring service / either path. Fresh installs after the revert get tokens under the legacy paths. |
| 3 | Re-point cloudflared at the old route. Re-add `luna-client-build.yaml`. **Bundle-ID change cannot be reverted cleanly** — users who installed the new app keep the new bundle; downgrading means a fresh install of the old bundle. Documented one-way door. |
| 4 | Cleanup-only PR. Reverting restores the shims; nothing user-visible changes. |

## Verification checklist

Run after each PR. Per
[`feedback_verification_function`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/feedback_verification_function.md)
— evidence before assertions, every stage.

After PR 1:
- [ ] `grep -rn 'Luna OS' apps/ docs/ README.md CLAUDE.md AGENTS.md` returns
      0 hits (excluding archived changelogs and this plan's own quotes).
- [ ] `grep -rn 'apps/luna-client' README.md CLAUDE.md AGENTS.md
      CONTRIBUTING.md` returns 0 hits (path text references; dir rename
      lands in PR 3 but doc references update here for clarity).
- [ ] `grep -rn 'Agent.name' apps/api/app/services/users.py` shows
      `name="Luna"` is still there (Luna persona unchanged — sanity check
      that we didn't accidentally touch it).
- [ ] `pytest apps/api/tests` green.
- [ ] Tauri dev mode (`cd apps/luna-client && npm run tauri dev`) launches,
      main window title says "Alpha", spatial-HUD window title says "Alpha
      OS", tray tooltip says "Alpha — agentprovision OS", but the chat
      avatar still says "Luna" and Luna's persona prompt is still in
      effect (chat with Luna; verify she signs replies as Luna).
- [ ] Browser dev console logs show `[Alpha OS]` for OS-shell events and
      `[Luna]` for persona events (distinct prefixes preserved).
- [ ] Existing user with `luna_token` in localStorage stays logged in
      (shim moved it to `alpha_token`).

After PR 2:
- [ ] `cargo build --workspace` clean.
- [ ] `cargo test --workspace` clean.
- [ ] Workspace `Cargo.toml` lists `apps/alpha-cli` + `apps/alpha-core`;
      no remaining `apps/agentprovision-cli` / `apps/agentprovision-core`
      paths.
- [ ] Existing CLI install: `alpha status` reports authenticated without
      re-login (keyring shim worked). The legacy keyring entry is gone
      after first read; the new one exists.
- [ ] Fresh CLI install: token lands under `"alpha"` keyring service;
      `~/Library/Application Support/alpha/` directory exists; no
      `agentprovision/` directory created.
- [ ] Both `ALPHA_TOKEN_FILE=... alpha status` and
      `AGENTPROVISION_TOKEN_FILE=... alpha status` work; the latter
      prints the deprecation warning once.
- [ ] `alpha chat send "hi"` still reaches Luna (verify reply persona is
      Luna's voice; she should sign as Luna).

After PR 3:
- [ ] `docker compose up -d --force-recreate alpha-client` brings up the
      desktop service on port `${ALPHA_PORT:-8009}`.
- [ ] `apps/alpha-client/` exists in the tree; `apps/luna-client/` gone.
      Inner `src/components/luna/` directory still present (renders Luna
      persona).
- [ ] `https://alpha.agentprovision.com` returns 200 and serves the
      desktop client.
- [ ] `https://luna.agentprovision.com` still returns 200 (parallel
      route active for the cleanup window).
- [ ] Existing macOS Luna install receives the final `luna-vX.Y.Z`
      update notification with the cutover banner copy linking to
      `agentprovision.com/download`.
- [ ] Fresh install of `Alpha.app` writes its bundle to
      `com.agentprovision.alpha` (`defaults read com.agentprovision.alpha`
      succeeds). The old `com.agentprovision.luna` defaults entry, if
      present, is untouched.
- [ ] Helm values file `agentprovision-alpha-client-local.yaml` exists;
      `agentprovision-luna-client-local.yaml` gone.

After PR 4:
- [ ] `grep -rn 'luna' apps/ helm/ kubernetes/ docker-compose.yml
      docs/cli/ README.md CLAUDE.md AGENTS.md CONTRIBUTING.md` returns
      only intentional residuals: `apps/alpha-client/src/components/luna/`
      and its files (persona renderers), `[Luna]` console prefix usages
      (persona events), references to "Luna the supervisor", migration
      filenames (123, 125), and this plan's own quoted-before-after table.
- [ ] cloudflared `luna.*` route removed; `https://luna.agentprovision.com`
      returns NXDOMAIN or 404.
- [ ] No new error log lines from missing legacy paths.

## Risks

- **Bundle-ID change forces reinstall.** No technical mitigation possible —
  macOS code-signing invariant. Mitigated by the final-Luna-release in-app
  banner and the release notes pointing at the download page. Acceptable.
- **Drift between docker-compose (active runtime) and Helm/K8s
  (aspirational per CLAUDE.md).** Per the user's
  [`feedback_no_local_builds`](../../../../.claude/projects/-Users-nomade-Documents-GitHub-servicetsunami-agents/memory/feedback_no_local_builds.md)
  rule and the helm-and-git-and-terraform sync rule, all surfaces get the
  rename in PR 3 even though only compose is the active runtime today.
- **`apps/.../src/components/luna/` looks wrong inside `apps/alpha-client/`
  after PR 3.** That's intentional: the directory name reflects that the
  components render Luna the persona, even though they ship inside the
  Alpha app shell. Add a one-line README inside the directory after PR 3
  explaining the family-model context so the next reader doesn't try to
  "fix" it.

## Follow-ups (out of scope here)

- **Alpha OS capability extensions.** Now that the family model is named,
  the work of *making Alpha OS more useful* (Tauri panel showing live
  `alpha` CLI sessions, `/cli <task>` shortcut in chat that dispatches via
  the CLI control plane, HUD nebula leaves orbiting an Alpha core, etc.)
  is its own PR series rooted in
  [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](2026-05-13-ap-cli-differentiation-roadmap.md)
  and the Alpha Control Plane work at `/den`. Not in this rebrand.
- **Luna persona evolution.** Now that Luna's identity is decoupled from
  the OS-shell rename, future persona work (voice tuning, multi-language,
  per-tenant persona overrides) has a clean roadmap of its own. Separate
  plan when wanted.
- **Documentation pass on `docs/changelog/*.md`.** Leave historical entries
  describing "Luna OS" or "Luna client" untouched (dated records of what
  shipped under the old framing); only flip prose in present-tense
  reference docs.
- **A new top-level docs section explaining the product family** — likely
  belongs at the top of README.md and as a brief callout in CLAUDE.md.
  Drafted as part of PR 1 above.
