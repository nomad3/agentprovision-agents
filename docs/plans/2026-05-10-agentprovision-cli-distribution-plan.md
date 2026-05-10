# Plan — `agentprovision` CLI PR-D: Multi-Platform Distribution + No-Admin Install

**Owner:** `apps/agentprovision-cli` + `apps/agentprovision-core` + new `.github/workflows/cli-release.yaml` + new install scripts hosted by `apps/api`
**Why:** PR-A (core extraction) and PR-B (skeleton) are in. PR-D turns the binary into a product surface — anyone in any company installs `agentprovision` with one curl, no sudo, on any of six platforms. Distribution surface = product surface; the install command is the first user impression. Reference UX: `gh`'s release flow, `rustup`'s install.sh, `claude` Pro's npm wrapper, `uv`'s install.ps1.
**Source design doc:** `docs/plans/2026-05-09-agentprovision-cli-design.md` §5 PR-D.

## Goal

Ship `agentprovision` to six target triples through GitHub Releases on every `cli-v*` tag, expose it through a hosted `curl | sh` and `iwr | iex` flow that installs without admin/root privileges, give it a baked-in `agentprovision upgrade` self-update path, and add a Homebrew tap + `cargo install` for users who already live in those package managers.

## Hard constraints (PR-D ship gate)

(a) On a fresh GitHub Codespace, `curl -fsSL https://agentprovision.com/install.sh | sh` lands a working `agentprovision` in `~/.local/bin` and exits clean. No sudo. No system package install.
(b) On a fresh Windows 11 sandbox, `iwr -useb https://agentprovision.com/install.ps1 | iex` lands `agentprovision.exe` in `%USERPROFILE%\.agentprovision\bin` and persists the User PATH update. No UAC prompt.
(c) `cli-v0.1.0` tag push produces six binaries plus checksums in a single GitHub Release within 25 minutes. Build is reproducible (locked Cargo.lock, `--frozen`).
(d) `agentprovision upgrade` on a 0.1.0 binary fetches and atomically replaces itself with 0.1.1, verifies SHA256, and survives an interrupted download (binary on disk is either fully old or fully new — never half-written).
(e) `brew install nomad3/agentprovision/agentprovision` installs on macos-14 and macos-13.
(f) `cargo install agentprovision-cli` works from crates.io once `agentprovision-core` is published.

## Phases

PR-D is too large for one PR. Split into five sequential pull requests; only PR-D-1 → PR-D-2 → PR-D-3 is on the critical path for "anyone in any company installs without admin." PR-D-4 (self-update) and PR-D-5 (Homebrew/cargo) are quality-of-life follow-ups.

| PR | Scope | Effort | Gates |
|---|---|---|---|
| PR-D-1 | Cross-compile build matrix (CI-only, no Release) | M | none |
| PR-D-2 | GitHub Actions release workflow on `cli-v*` tag | M | PR-D-1 |
| PR-D-3 | `install.sh` + `install.ps1` + hosting endpoint | M | PR-D-2 |
| PR-D-4 | `agentprovision upgrade` self-update subcommand | S | PR-D-2 |
| PR-D-5 | Homebrew tap + `cargo install` | S | PR-D-2 |

Total: ~M + M + M + S + S, roughly 8–10 engineering days.

## PR-D-1 — Cross-compile build matrix

### Targets (six)

| Target triple | Runner | Strategy | Artifact name |
|---|---|---|---|
| `aarch64-apple-darwin` | `macos-14` | native | `agentprovision-aarch64-apple-darwin.tar.gz` |
| `x86_64-apple-darwin` | `macos-13` | native | `agentprovision-x86_64-apple-darwin.tar.gz` |
| `x86_64-unknown-linux-musl` | `ubuntu-22.04` | `cargo zigbuild` | `agentprovision-x86_64-unknown-linux-musl.tar.gz` |
| `aarch64-unknown-linux-musl` | `ubuntu-22.04` | `cargo zigbuild` | `agentprovision-aarch64-unknown-linux-musl.tar.gz` |
| `x86_64-pc-windows-msvc` | `windows-latest` | native | `agentprovision-x86_64-pc-windows-msvc.zip` |
| `aarch64-pc-windows-msvc` | `windows-latest` | cross-compile from x64 | `agentprovision-aarch64-pc-windows-msvc.zip` |

### Build-tool decision: `cargo zigbuild` for both Linux musl targets

Three options were considered: `cross` crate (Docker-based, slow on CI without cache), `cargo zigbuild` (Zig-as-linker, lighter and faster, no Docker), native runner per target. **Decision: native where possible (macOS + Windows x64), `cargo zigbuild` for Linux musl + Windows ARM64 cross-compile.**

### Linux: musl-only, no glibc

- Pure-Rust stack — no system libs to bind against (rustls + keyring + reqwest all pure Rust). musl is portable across every distro from Alpine to RHEL 8.
- One linux artifact per arch keeps install.sh logic trivially simple.
- `gh` CLI ships glibc and gets occasional bug reports from old-distro users; we pre-empt them.

### Reproducible builds

- `Cargo.lock` committed; CI uses `cargo build --release --locked --frozen --target <triple>`.
- Pin Rust toolchain via `rust-toolchain.toml` at workspace root.
- Strip debuginfo on Linux + macOS.
- Cache Cargo registry + target dir per-OS.

### Code signing

| Platform | Decision |
|---|---|
| macOS | **Sign + notarize.** Reuse Luna's `APPLE_ID`/`APPLE_PASSWORD`/`APPLE_TEAM_ID` secrets. Without notarization, downloaded binaries get the "cannot be opened" Gatekeeper dialog. 3x retry on flake. |
| Linux | Plain binary, no-op. |
| Windows | **Defer to PR-D-1.5.** SmartScreen warns on unsigned exes for ~30 days/until reputation accrues. PR-D-1 ships unsigned with a clear "click 'More info' → 'Run anyway' on first launch" note. PR-D-1.5 follows once we register a code-signing cert. |

### Files created/changed

| File | Action |
|---|---|
| `rust-toolchain.toml` (workspace root) | new |
| `.github/workflows/cli-build-matrix.yaml` | new |
| `apps/agentprovision-cli/Cargo.toml` | edit — explicit `[profile.release] strip = "symbols", lto = "thin", codegen-units = 1` |
| `apps/agentprovision-cli/.cargo/config.toml` | new — per-target linker hints for zigbuild |

### Acceptance criteria

- `cli-build-matrix.yaml` is green on a draft PR — six artifacts uploaded, each verified runnable on its target.
- Cold build < 12 min/job; warm < 6 min.
- Each artifact < 15 MB stripped.

## PR-D-2 — Release workflow on `cli-v*` tag

### Trigger

```yaml
on:
  push:
    tags: ['cli-v*']
  workflow_dispatch:
    inputs:
      version:
        description: 'Version (e.g. 0.1.0)'
        required: true
```

Matches the existing `luna-v*` convention; CLI release independent from API release.

### Jobs

```
build (matrix: 6 targets)
  - checkout, install rust, install zig (linux only)
  - cargo build/zigbuild --release --locked
  - strip + sign + notarize (macos)
  - tar.gz / zip + SHA256
  - upload artifact

release (depends on build)
  - download all 6
  - concatenate SHA256SUMS
  - generate release notes + Install header
  - gh release create cli-v$VERSION

post-release (depends on release)
  - bump Homebrew formula (PR-D-5)
  - cargo publish (PR-D-5)
```

### Versioning + artifact naming

- Source of truth: `apps/agentprovision-cli/Cargo.toml` `version`.
- Tag format: `cli-v<VERSION>`.
- Workflow validates `Cargo.toml` version == tag-stripped. Hard-fail on mismatch.
- Artifact: `agentprovision-<TARGET_TRIPLE>.<EXT>`. Each archive contains `agentprovision[.exe]`, `LICENSE`, `README.md`, `agentprovision.1` man page.

### `SHA256SUMS` manifest

`sha256sum -c`-compatible. `cosign` keyless signing deferred to PR-D-1.5.

### Files

| File | Action |
|---|---|
| `.github/workflows/cli-release.yaml` | new |
| `apps/agentprovision-cli/build.rs` | new — `clap_mangen` man-page emit |
| `apps/agentprovision-cli/Cargo.toml` | edit — `[build-dependencies] clap_mangen = "0.2"` |

### Acceptance criteria

- `cli-v0.1.0-rc1` tag → draft Release with all 6 artifacts + SHA256SUMS in <25min.
- `sha256sum -c` succeeds on every artifact.
- macOS artifacts pass `spctl -a` after notarization.
- Re-running on the same tag idempotent (`gh release upload --clobber`).

## PR-D-3 — Install scripts + hosting

### `install.sh` (POSIX)

Zero deps beyond `curl`, `tar`, `uname`, `mkdir`, `mv`, `chmod`, `sha256sum`/`shasum`. Mirrors `rustup-init.sh`.

```
1. Refuse sudo: [ "$(id -u)" = "0" ] && err
2. Detect OS:   uname -s → Darwin | Linux
3. Detect arch: uname -m → x86_64 | aarch64 (arm64 → aarch64)
4. Map triple
5. Resolve version (latest via /releases/latest API; AGENTPROVISION_VERSION env override)
6. curl -fsSL --retry 3 the tar.gz
7. SHA verify against SHA256SUMS
8. tar -xzf to $TMP
9. mkdir -p ~/.local/bin && mv binary
10. PATH check: print export one-liner if not present.
    DO NOT auto-edit shell rc unless --add-to-path
11. Man page: ~/.local/share/man/man1/agentprovision.1
12. echo "Run 'agentprovision login' to authenticate"
13. trap EXIT cleanup $TMP
```

#### Flags

`--version`, `--prefix`, `--add-to-path`, `--no-modify-path`, `--quiet`. Honour `AGENTPROVISION_VERSION` env.

### `install.ps1` (PowerShell)

Mirror of install.sh. Refuses elevated session, downloads + verifies SHA, extracts to `%USERPROFILE%\.agentprovision\bin`, updates User-scope PATH via `[Environment]::SetEnvironmentVariable(... 'User')` (no UAC).

### Hosting at `agentprovision.com/install.sh`

**Decision: FastAPI route.** `apps/api/app/api/v1/install_scripts.py` with two endpoints (`GET /install.sh`, `GET /install.ps1`). Sources from `apps/api/static/install/`. Versioned via git, deploys with API.

- `Cache-Control: public, max-age=300`
- `Content-Type: text/x-shellscript` for sh, `application/x-powershell` for ps1
- Unauthenticated allow-list

Mirror to GitHub Releases: every release attaches install.sh as an asset, so `curl github.com/.../releases/latest/download/install.sh` is a fallback if API is down.

### Files

| File | Action |
|---|---|
| `apps/agentprovision-cli/install/install.sh` | new — source of truth |
| `apps/agentprovision-cli/install/install.ps1` | new |
| `apps/api/static/install/install.sh` | symlink/CI-synced copy |
| `apps/api/static/install/install.ps1` | symlink/CI-synced copy |
| `apps/api/app/api/v1/install_scripts.py` | new |
| `apps/api/app/api/v1/routes.py` | edit — mount router |
| `apps/agentprovision-cli/install/test/test_install_sh.bats` | new |
| `apps/agentprovision-cli/install/test/test_install_ps1.ps1` | new |

### Acceptance criteria

- `curl -fsSL https://agentprovision.com/install.sh | sh` on fresh GitHub Codespace — `agentprovision login --help` works in <30s.
- `iwr -useb https://agentprovision.com/install.ps1 | iex` on fresh Windows 11 Sandbox — same, no UAC.
- `id -u == 0` exits 1 with "do not use sudo".
- Tampered SHA exits 1 with "checksum mismatch".
- Re-run upgrades cleanly (no duplicate PATH lines).
- Bats + Pester smoke tests in CI.

## PR-D-4 — `agentprovision upgrade` self-update subcommand

### Approach

Use [`self_update`](https://crates.io/crates/self_update) crate with rustls features. GitHub Releases backend, per-target asset matching, atomic file replacement, SHA256 verification.

### Subcommand

```
agentprovision upgrade
agentprovision upgrade --check
agentprovision upgrade --version 0.1.5
agentprovision upgrade --prerelease
```

### Edge cases

- **macOS Gatekeeper**: new binary inherits quarantine xattr. Wrapper calls `xattr -d com.apple.quarantine` after rename.
- **Windows running-binary lock**: `self_update`'s pattern of rename `.exe` → `.exe.old`, drop new in place. Works.
- **brew/cargo-managed install**: detect by binary path; if `/opt/homebrew/`, `/usr/local/Cellar/`, or `~/.cargo/bin/`, refuse with "use brew upgrade / cargo install --force".

### Files

| File | Action |
|---|---|
| `apps/agentprovision-cli/Cargo.toml` | edit — `self_update = { version = "0.39", features = ["rustls", "archive-tar", "archive-zip", "compression-flate2"], default-features = false }` |
| `apps/agentprovision-cli/src/commands/upgrade.rs` | new |
| `apps/agentprovision-cli/src/commands/mod.rs` + `cli.rs` | edit — register |
| `apps/agentprovision-cli/README.md` | edit |

### Acceptance criteria

- `upgrade --check` on 0.1.0 vs. 0.1.1 release prints `update available`.
- `upgrade` replaces atomically; `--version` reports new.
- Tampered SHA aborts cleanly.
- Run from `/opt/homebrew/bin/` exits with brew/cargo guidance.

## PR-D-5 — Homebrew tap + `cargo install`

### Homebrew tap

New repo: `nomad3/homebrew-agentprovision`. Single formula at `Formula/agentprovision.rb` covering `on_macos { on_arm | on_intel }` and `on_linux { on_arm | on_intel }`. Auto-bumped via [`mislav/bump-homebrew-formula-action`](https://github.com/mislav/bump-homebrew-formula-action) (the same action `gh` uses) in the `post-release` job. Requires `HOMEBREW_TAP_TOKEN` repo secret.

Install command: `brew install nomad3/agentprovision/agentprovision`.

### `cargo install` from crates.io

Two crates published in order: `agentprovision-core` first, then `agentprovision-cli`. Cargo.toml metadata already populated.

```
cargo publish -p agentprovision-core --token $CARGO_REGISTRY_TOKEN
sleep 30   # crates.io index lag
cargo publish -p agentprovision-cli --token $CARGO_REGISTRY_TOKEN
```

Risks:
- Path-only deps rejected by crates.io. Verify `cargo publish --dry-run` passes.
- Name squat. Reserve names in PR-D-5's first commit even if unused.

### Files

| File | Action | Repo |
|---|---|---|
| `nomad3/homebrew-agentprovision` | new repo | external |
| `Formula/agentprovision.rb` | new | external |
| `.github/workflows/cli-release.yaml` | edit — add `post-release` job | this repo |

### Acceptance criteria

- `brew install nomad3/agentprovision/agentprovision` works on macos-14 + macos-13 + ubuntu-22.04 (linuxbrew).
- `cargo install agentprovision-cli` from fresh cargo install works.
- Tagging `cli-v0.1.1` auto-PRs the bump + auto-publishes both crates.

## Documentation surface (incremental)

| File | What changes | Phase |
|---|---|---|
| `apps/agentprovision-cli/README.md` | Install section at top with curl/iwr one-liners + brew + cargo | D-3, D-5 |
| `README.md` (repo root) | "CLI install" subsection | D-3 |
| `apps/web/src/pages/CliPage.js` (new route `/cli`) | Hero with install one-liners, OS-aware, copy-to-clipboard | D-3 |
| `apps/agentprovision-cli/man/agentprovision.1` | Auto-gen at build, snapshot committed | D-2 |
| `docs/cli-install.md` | Full guide — every platform, troubleshooting | D-3 |

## Dependency graph

```
PR-D-1 (build matrix)
  └─► PR-D-2 (release workflow)
        ├─► PR-D-3 (install scripts + hosting)  ← unblocks curl|sh story
        ├─► PR-D-4 (self-update)
        └─► PR-D-5 (Homebrew + cargo)
```

**Critical path: D-1 → D-2 → D-3.** Three PRs, ~5 engineer-days.

## Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| macOS notarization flakes | M | M | 3x retry; manual workflow_dispatch override |
| Windows SmartScreen on unsigned .exe | H (initial) | M | Document "More info → Run anyway"; PR-D-1.5 buys OV cert |
| zigbuild compatibility regression on Rust upgrade | L | M | Pin `rust-toolchain.toml`; bump deliberately |
| `agentprovision.com/install.sh` host down | L | H | GitHub Releases mirror as fallback |
| crates.io name squat | M | H | Reserve names in PR-D-5 first commit |
| `agentprovision upgrade` corrupts running binary | L | H | `self_update` proven; install.sh as escape hatch |
| install.sh runs as root | L | H | `id -u == 0` guard |
| Notarization secrets leak in CI | L | H | `secrets.APPLE_ID` + `add-mask`; mirror luna-client-build pattern |
| `~/.local/bin` not on PATH (Alpine, RHEL) | M | M | Print export one-liner; `--add-to-path` opt-in |

## Effort sizing

| Phase | Sizing |
|---|---|
| D-1 build matrix | M (~2 days) |
| D-2 release workflow | M (~2 days) |
| D-3 install scripts | M (~2 days) |
| D-4 self-update | S (~1 day) |
| D-5 Homebrew + cargo | S (~1 day) |
| **Total** | **~8 engineer-days** |

## Definition of Done

- ✅ Six binaries ship on every `cli-v*` tag, signed where possible, with SHA256 manifest
- ✅ `curl https://agentprovision.com/install.sh | sh` works on macOS arm64/x64, Linux x64/ARM64
- ✅ `iwr https://agentprovision.com/install.ps1 | iex` works on Windows x64/ARM64
- ✅ No phase requires sudo, root, or admin elevation
- ✅ `agentprovision upgrade` atomic + SHA-verified
- ✅ `brew install nomad3/agentprovision/agentprovision` works
- ✅ `cargo install agentprovision-cli` works
- ✅ README + man page + landing `/cli` page live
- ✅ Bats + Pester install smoke tests pass in CI
- ✅ All PRs assigned to nomad3, no AI credit lines

## Cross-references

- Source design: `docs/plans/2026-05-09-agentprovision-cli-design.md` §5 PR-D
- Phase 2 plan: `docs/plans/2026-05-09-agentprovision-cli-phase-2-temporal-rl-memory.md`
- Existing release pattern: `.github/workflows/luna-client-build.yaml` (Tauri DMG; reuse Apple secrets)
- CLI source: `apps/agentprovision-cli/`
- Core lib: `apps/agentprovision-core/` (rustls-tls, keyring v2 — pure Rust, no system libs)
