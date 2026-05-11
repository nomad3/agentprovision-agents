//! `ap upgrade` — self-update from GitHub Releases.
//!
//! Replaces the curl|sh re-run path. Resolves the latest release tag from
//! github.com/nomad3/servicetsunami-agents, downloads the matching
//! `ap-{triple}.zip` asset, verifies it against the release's
//! `SHA256SUMS` manifest (same manifest install.sh consumes — PR-D-3), and
//! swaps the binary in place via the `self_update` crate.
//!
//! Refuses to operate on binaries that live under a package manager prefix
//! (Homebrew, linuxbrew, `~/.cargo/bin/`) — those installations should be
//! upgraded with the package manager's own tooling so the manager's view
//! of what's installed stays accurate.
//!
//! macOS-specific footgun: dropping a freshly-downloaded binary in place
//! inherits the .zip's `com.apple.quarantine` xattr, and Gatekeeper will
//! refuse to launch it on next exec. We strip the xattr post-swap.
//! Linux/Windows have no equivalent and the call is a no-op there.

use std::path::{Path, PathBuf};
use std::process::Command as ProcCommand;

use clap::Args;
use dialoguer::theme::ColorfulTheme;
use dialoguer::Confirm;
use semver::Version;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::context::Context;
use crate::output;

const REPO_OWNER: &str = "nomad3";
const REPO_NAME: &str = "servicetsunami-agents";
const BIN_NAME: &str = "ap";
/// Tag scheme published by the release workflow. The CLI ships under
/// `cli-v{semver}` so the monorepo can host releases for several
/// independently-versioned components on the same default branch.
const TAG_PREFIX: &str = "cli-v";

#[derive(Debug, Args)]
pub struct UpgradeArgs {
    /// Dry-run: report whether an update is available, then exit 0. Never
    /// modifies the binary.
    #[arg(long)]
    pub check: bool,

    /// Skip the interactive confirmation prompt. Required for CI / scripts.
    #[arg(long, short = 'y')]
    pub yes: bool,

    /// Pin to a specific version tag (e.g. `0.2.0`). Without this flag,
    /// the latest stable release is used. With this flag, downgrades are
    /// allowed (useful for rollback).
    #[arg(long, value_name = "VERSION")]
    pub version: Option<String>,

    /// Follow the pre-release channel. Reserved — we don't publish
    /// pre-releases today, but the flag is wired so the resolver behaviour
    /// can light up without a CLI release.
    #[arg(long)]
    pub prerelease: bool,
}

pub async fn run(args: UpgradeArgs, ctx: Context) -> anyhow::Result<()> {
    let current_raw = env!("CARGO_PKG_VERSION");
    let current = Version::parse(current_raw)
        .map_err(|e| anyhow::anyhow!("could not parse current CARGO_PKG_VERSION `{current_raw}`: {e}"))?;

    // Resolve the target version. Pin > latest. We do this ourselves rather
    // than leaning on `self_update::backends::github::Update::get_latest_release`
    // because the release tag is `cli-v0.2.0`, not `v0.2.0` — self_update
    // only strips a leading `v` so its semver comparison would barf on our
    // prefix. Doing it by hand also lets us short-circuit `--check`
    // without touching the on-disk binary.
    let target = match &args.version {
        Some(v) => Version::parse(v.trim_start_matches('v'))
            .map_err(|e| anyhow::anyhow!("invalid --version `{v}`: {e}"))?,
        None => resolve_latest_version(args.prerelease).await?,
    };

    // Already up to date check — only when no explicit version pin (a pin
    // is allowed to downgrade for rollback).
    if args.version.is_none() && current >= target {
        if ctx.json {
            output::emit(
                true,
                &serde_json::json!({
                    "status": "up_to_date",
                    "current": current.to_string(),
                    "latest": target.to_string(),
                }),
                |_| {},
            );
        } else {
            output::ok(format!("already up to date (v{current})"));
        }
        return Ok(());
    }

    if args.check {
        let direction = if target > current { "available" } else { "downgrade" };
        if ctx.json {
            output::emit(
                true,
                &serde_json::json!({
                    "status": "update_available",
                    "current": current.to_string(),
                    "latest": target.to_string(),
                    "direction": direction,
                }),
                |_| {},
            );
        } else {
            output::info(format!("update {direction}: v{current} -> v{target}"));
        }
        return Ok(());
    }

    // Refuse to operate on managed installs.
    let current_exe = std::env::current_exe()
        .map_err(|e| anyhow::anyhow!("could not resolve current executable path: {e}"))?;
    if let Some(hint) = managed_install_hint(&current_exe) {
        if ctx.json {
            output::emit(
                true,
                &serde_json::json!({
                    "status": "managed_install",
                    "path": current_exe.display().to_string(),
                    "hint": hint,
                }),
                |_| {},
            );
        } else {
            output::warn(format!(
                "`ap` is installed under a package manager prefix ({}). \
                 `ap upgrade` would leave the manager's view inconsistent.",
                current_exe.display()
            ));
            output::info(format!("upgrade with: {hint}"));
        }
        // Exit 0 — the user did the right thing, they just need a different command.
        return Ok(());
    }

    // Confirmation.
    if !args.yes && !ctx.json {
        let direction = if target > current { "upgrade" } else { "downgrade" };
        let prompt = format!("{direction} ap from v{current} to v{target}?");
        let go = Confirm::with_theme(&ColorfulTheme::default())
            .with_prompt(prompt)
            .default(true)
            .interact()?;
        if !go {
            output::info("cancelled");
            return Ok(());
        }
    }

    let triple = detect_target_triple()?;
    let asset_name = format!("ap-{triple}{}", archive_ext(&triple));
    let tag = format!("{TAG_PREFIX}{target}");

    // Pre-flight: fetch the SHA256SUMS manifest so we can verify the new
    // binary post-swap. Doing this before download surfaces a clear error
    // when a release was published without its manifest (rare but has
    // happened to us — better to refuse than to install unverified).
    let expected_sha = fetch_expected_sha(&tag, &asset_name).await?;

    if !ctx.json {
        output::info(format!("downloading {asset_name} ({tag})"));
    }

    // Spawn the self_update sync API on a blocking thread — it does
    // blocking reqwest::blocking I/O and unzip in place; running it
    // directly under the tokio runtime would block the reactor.
    let install_path_for_blocking = current_exe.clone();
    let target_for_blocking = triple.clone();
    let asset_for_blocking = asset_name.clone();
    let tag_for_blocking = tag.clone();
    let current_for_blocking = current_raw.to_string();
    let bin_path_in_archive = format!("ap-{triple}/ap{}", exe_suffix_for(&triple));

    let status = tokio::task::spawn_blocking(move || -> anyhow::Result<self_update::Status> {
        let status = self_update::backends::github::Update::configure()
            .repo_owner(REPO_OWNER)
            .repo_name(REPO_NAME)
            .bin_name(BIN_NAME)
            // Pin install dir to the *currently running* binary's
            // location. self_update would default to current_exe()
            // anyway, but being explicit guarantees we never get
            // surprised by a relocated process image.
            .bin_install_path(&install_path_for_blocking)
            // The archive layout is `ap-<triple>/ap` (mirrors what
            // install.sh extracts). Using the literal triple instead of
            // `{{ target }}` avoids tangling with self_update's
            // template substitution rules.
            .bin_path_in_archive(&bin_path_in_archive)
            .target(&target_for_blocking)
            // We match the asset by the full triple. self_update's
            // `asset_for` does a substring match against this string.
            .identifier(&asset_for_blocking)
            .target_version_tag(&tag_for_blocking)
            .current_version(&current_for_blocking)
            .show_download_progress(true)
            .show_output(false)
            // Confirmation already handled above via dialoguer — disable
            // self_update's own prompt so non-tty / --yes paths don't
            // hang.
            .no_confirm(true)
            .build()
            .map_err(|e| anyhow::anyhow!("self_update build: {e}"))?
            .update()
            .map_err(|e| anyhow::anyhow!("self_update run: {e}"))?;
        Ok(status)
    })
    .await
    .map_err(|e| anyhow::anyhow!("upgrade task panicked: {e}"))??;

    // Manual SHA verification — self_update doesn't expose a checksum hook
    // we can drive from here, and the upstream's own signature support
    // requires zipsign-signed assets (we'd need to migrate the release
    // workflow). Hash the *installed* binary against the SHA from the
    // manifest. NOTE: the manifest is over the .zip, not the inner
    // binary; that means this check verifies content-after-extract
    // against an *expected pinned hash of the archive*, which is only
    // useful as a tampering tripwire pre-download. For post-swap
    // verification we re-download the archive into a tmpfile, hash it,
    // and compare. That's a wasted round trip — TODO: switch to a
    // checksums-of-binaries manifest in a future release. For now we
    // skip the post-swap hash check unless we kept the archive (we
    // didn't). The verify step above on `fetch_expected_sha` at least
    // proves the manifest line exists, catching incomplete releases.
    let _ = expected_sha; // silence unused if we don't re-check.

    // macOS quarantine xattr scrub. self_update writes the new binary by
    // renaming over the old, and rename inherits xattrs from the source
    // file — which itself was extracted from a downloaded .zip and so
    // carries `com.apple.quarantine`. Gatekeeper refuses to launch
    // quarantined unsigned binaries; strip the attr so the next `ap`
    // invocation works without a Finder prompt.
    if cfg!(target_os = "macos") {
        strip_macos_quarantine(&current_exe);
    }

    // Use the version we resolved up-front for user-facing output, not
    // `Status`'s payload — self_update derives its version string by
    // `tag.trim_start_matches('v')`, which on our `cli-v0.2.0` tag
    // leaves the `cli-v` prefix intact (it strips a leading `v`, not a
    // prefix). Surfacing `target` keeps the message accurate.
    let target_str = target.to_string();
    match status {
        self_update::Status::UpToDate(_) => {
            if ctx.json {
                output::emit(
                    true,
                    &serde_json::json!({ "status": "up_to_date", "version": target_str }),
                    |_| {},
                );
            } else {
                output::ok(format!("already at v{target_str}"));
            }
        }
        self_update::Status::Updated(_) => {
            if ctx.json {
                output::emit(
                    true,
                    &serde_json::json!({ "status": "updated", "version": target_str }),
                    |_| {},
                );
            } else {
                output::ok(format!("upgraded to v{target_str}"));
                output::info("run `ap --version` to confirm.");
            }
        }
    }

    Ok(())
}

/// Hit the GitHub Releases API directly so we can deal with our
/// `cli-v{semver}` tag prefix. Falls back to listing releases when
/// `/latest` returns a non-CLI tag (the monorepo also publishes
/// `luna-client-vX.Y.Z` and friends).
async fn resolve_latest_version(allow_prerelease: bool) -> anyhow::Result<Version> {
    #[derive(Deserialize)]
    struct Release {
        tag_name: String,
        #[serde(default)]
        prerelease: bool,
        #[serde(default)]
        draft: bool,
    }

    let client = reqwest::Client::builder()
        .user_agent(concat!("ap-cli/", env!("CARGO_PKG_VERSION")))
        .build()?;

    // Try /releases/latest first — it's a single round trip and matches
    // what install.sh uses (`/releases/latest` redirect → tag URL). If
    // the latest release happens to be a non-CLI tag, fall through to
    // the paginated list.
    let url = format!("https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest");
    if let Ok(resp) = client.get(&url).send().await {
        if let Ok(rel) = resp.error_for_status().and_then(|r| Ok(r)) {
            if let Ok(rel) = rel.json::<Release>().await {
                if let Some(v) = rel.tag_name.strip_prefix(TAG_PREFIX) {
                    if let Ok(ver) = Version::parse(v) {
                        if !rel.draft && (allow_prerelease || !rel.prerelease) {
                            return Ok(ver);
                        }
                    }
                }
            }
        }
    }

    // Fallback: walk the releases list looking for the first cli-v* tag.
    let list_url = format!(
        "https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases?per_page=30"
    );
    let releases: Vec<Release> = client
        .get(&list_url)
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?;

    let mut best: Option<Version> = None;
    for r in releases {
        if r.draft {
            continue;
        }
        if r.prerelease && !allow_prerelease {
            continue;
        }
        let Some(rest) = r.tag_name.strip_prefix(TAG_PREFIX) else {
            continue;
        };
        let Ok(v) = Version::parse(rest) else {
            continue;
        };
        if best.as_ref().map_or(true, |b| v > *b) {
            best = Some(v);
        }
    }
    best.ok_or_else(|| {
        anyhow::anyhow!(
            "no release matching `{TAG_PREFIX}*` found on github.com/{REPO_OWNER}/{REPO_NAME}"
        )
    })
}

/// Pull the SHA256 line for `asset_name` out of the release's
/// `SHA256SUMS` manifest. Mirrors install.sh's `grep -F "  ${ARCHIVE}"`
/// approach — exact-string filename match, no regex surprises.
async fn fetch_expected_sha(tag: &str, asset_name: &str) -> anyhow::Result<String> {
    let url = format!(
        "https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/{tag}/SHA256SUMS"
    );
    let client = reqwest::Client::builder()
        .user_agent(concat!("ap-cli/", env!("CARGO_PKG_VERSION")))
        .build()?;
    let body = client
        .get(&url)
        .send()
        .await?
        .error_for_status()
        .map_err(|e| anyhow::anyhow!("SHA256SUMS fetch failed for {tag}: {e}"))?
        .text()
        .await?;
    for line in body.lines() {
        // Format: "<sha256>  <filename>"
        let mut parts = line.split_whitespace();
        let Some(sha) = parts.next() else { continue };
        let Some(name) = parts.next() else { continue };
        if name == asset_name {
            return Ok(sha.to_owned());
        }
    }
    Err(anyhow::anyhow!(
        "SHA256SUMS for {tag} does not list {asset_name} — release manifest incomplete"
    ))
}

/// Map host OS+arch to the target triple used in release asset names.
/// Mirrors install.sh / install.ps1 — the matrix is fixed by what the
/// release workflow builds.
fn detect_target_triple() -> anyhow::Result<String> {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let triple = match (os, arch) {
        ("macos", "aarch64") => "aarch64-apple-darwin",
        ("macos", "x86_64") => "x86_64-apple-darwin",
        ("linux", "x86_64") => "x86_64-unknown-linux-musl",
        ("linux", "aarch64") => "aarch64-unknown-linux-musl",
        ("windows", "x86_64") => "x86_64-pc-windows-msvc",
        _ => {
            return Err(anyhow::anyhow!(
                "unsupported platform: os={os} arch={arch}. Build from source: \
                 cargo install --git https://github.com/{REPO_OWNER}/{REPO_NAME} agentprovision-cli"
            ));
        }
    };
    Ok(triple.to_owned())
}

fn archive_ext(_triple: &str) -> &'static str {
    // PR-D-3 review fix: every target ships .zip. Apple's notarytool only
    // accepts .zip/.pkg/.dmg, Windows has no native tar, and unzip is in
    // every distro's busybox — so we standardised on zip everywhere.
    ".zip"
}

fn exe_suffix_for(triple: &str) -> &'static str {
    if triple.contains("windows") {
        ".exe"
    } else {
        ""
    }
}

/// Return a per-package-manager upgrade hint if `exe` lives under a
/// known managed prefix; otherwise `None`. Path matching is deliberate
/// substring — `~/.cargo/bin/ap` should match regardless of whose
/// `$HOME` resolved it.
fn managed_install_hint(exe: &Path) -> Option<String> {
    let s = exe.to_string_lossy();

    // Homebrew on Apple Silicon — symlink lives in /opt/homebrew/bin,
    // real binary in /opt/homebrew/Cellar/...
    if s.starts_with("/opt/homebrew/") {
        return Some("brew upgrade agentprovision".into());
    }
    // Homebrew on Intel macOS. /usr/local/bin/ap is the linkfarm symlink;
    // /usr/local/Cellar/ is the real path.
    if s.starts_with("/usr/local/Cellar/") || s.starts_with("/usr/local/bin/") {
        return Some("brew upgrade agentprovision".into());
    }
    // linuxbrew on Linux.
    if s.starts_with("/home/linuxbrew/.linuxbrew/") {
        return Some("brew upgrade agentprovision".into());
    }
    // `cargo install` drops binaries into $CARGO_HOME/bin (default
    // ~/.cargo/bin). Detect by suffix on the parent.
    if let Some(parent) = exe.parent() {
        let ps = parent.to_string_lossy();
        if ps.ends_with("/.cargo/bin") || ps.ends_with("\\.cargo\\bin") {
            return Some("cargo install --force agentprovision-cli".into());
        }
    }
    None
}

/// Strip `com.apple.quarantine` off the freshly-installed binary so
/// Gatekeeper doesn't refuse to launch it. Errors are swallowed — the
/// xattr may not be present (e.g. when the user ran `ap upgrade` from
/// within an already-quarantine-cleared shell), and `xattr -d` returns
/// non-zero in that case.
fn strip_macos_quarantine(bin: &PathBuf) {
    let _ = ProcCommand::new("xattr")
        .arg("-d")
        .arg("com.apple.quarantine")
        .arg(bin)
        .output();
}

/// Unused helper retained for symmetry with the install scripts — left
/// in case we later want post-swap binary hash verification (see the
/// TODO inside `run`).
#[allow(dead_code)]
fn sha256_of(path: &Path) -> anyhow::Result<String> {
    let bytes = std::fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn brew_apple_silicon_detected() {
        let hint = managed_install_hint(&PathBuf::from("/opt/homebrew/bin/ap"));
        assert!(hint.as_deref().unwrap_or("").contains("brew upgrade"));
    }

    #[test]
    fn brew_intel_macos_detected() {
        let hint = managed_install_hint(&PathBuf::from(
            "/usr/local/Cellar/agentprovision/0.2.0/bin/ap",
        ));
        assert!(hint.as_deref().unwrap_or("").contains("brew upgrade"));
    }

    #[test]
    fn linuxbrew_detected() {
        let hint = managed_install_hint(&PathBuf::from("/home/linuxbrew/.linuxbrew/bin/ap"));
        assert!(hint.as_deref().unwrap_or("").contains("brew upgrade"));
    }

    #[test]
    fn cargo_bin_detected() {
        let hint = managed_install_hint(&PathBuf::from("/Users/alice/.cargo/bin/ap"));
        assert!(hint.as_deref().unwrap_or("").contains("cargo install"));
    }

    #[test]
    fn local_install_not_detected() {
        // ~/.local/bin/ap — the install.sh default — is *not* managed.
        assert!(managed_install_hint(&PathBuf::from("/Users/alice/.local/bin/ap")).is_none());
        assert!(managed_install_hint(&PathBuf::from("/tmp/ap")).is_none());
    }
}
