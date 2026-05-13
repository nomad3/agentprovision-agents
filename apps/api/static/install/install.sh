#!/bin/sh
# shellcheck shell=sh
# install.sh — POSIX installer for the `alpha` CLI (AgentProvision).
#
# Usage (typical):
#   curl -fsSL https://agentprovision.com/install.sh | sh
#
# Usage (pin a version):
#   AGENTPROVISION_VERSION=0.2.0 curl -fsSL https://agentprovision.com/install.sh | sh
#
# Or with flags (after downloading the script first):
#   curl -fsSL https://agentprovision.com/install.sh -o install.sh
#   sh install.sh --version 0.2.0 --prefix $HOME/.local --add-to-path
#
# What it does:
#   1. Refuses to run as root (`--no-modify-path` to system locations).
#   2. Detects OS + arch, maps to a target triple (mac arm64/x64, linux x64
#      via the static musl binary, windows users use install.ps1 instead).
#   3. Resolves a concrete version (latest stable, or AGENTPROVISION_VERSION).
#   4. Downloads the matching release archive + verifies SHA256.
#   5. Extracts to a temp dir; moves `alpha` → ~/.local/bin/alpha.
#   6. Drops the man page at ~/.local/share/man/man1/alpha.1.
#   7. Prints PATH-export instructions if ~/.local/bin isn't already on PATH.
#   8. Cleans up.
#
# Idempotent: re-running upgrades cleanly. Use `alpha upgrade` instead once
# you have an install (PR-D-4 — coming soon).

set -eu

REPO="nomad3/servicetsunami-agents"
INSTALL_DIR="$HOME/.local/bin"
MAN_DIR="$HOME/.local/share/man/man1"
ADD_TO_PATH=0
QUIET=0
VERSION="${AGENTPROVISION_VERSION:-latest}"

# ── arg parsing ────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --version) VERSION="$2"; shift 2 ;;
        --prefix) INSTALL_DIR="$2/bin"; MAN_DIR="$2/share/man/man1"; shift 2 ;;
        --add-to-path) ADD_TO_PATH=1; shift ;;
        --no-modify-path) ADD_TO_PATH=0; shift ;;
        --quiet) QUIET=1; shift ;;
        --help|-h)
            sed -n '2,30p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) printf 'Unknown flag: %s\n' "$1" >&2; exit 2 ;;
    esac
done

say() { [ "$QUIET" = "1" ] || printf '%s\n' "$*"; }
err() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# ── refuse sudo ────────────────────────────────────────────────────────────
if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then
    err "do not run with sudo. alpha installs into \$HOME/.local/bin (no admin needed). If you need a system-wide install, set --prefix /usr/local explicitly and run as that user."
fi

# ── detect OS + arch ───────────────────────────────────────────────────────
OS=$(uname -s 2>/dev/null || echo unknown)
ARCH=$(uname -m 2>/dev/null || echo unknown)

case "$ARCH" in
    arm64|aarch64) ARCH=aarch64 ;;
    x86_64|amd64)  ARCH=x86_64 ;;
    *) err "unsupported architecture: $ARCH" ;;
esac

case "$OS" in
    Darwin)
        TRIPLE="${ARCH}-apple-darwin"
        # macOS ships .zip — Apple's xcrun notarytool only accepts
        # .zip / .pkg / .dmg, so PR-D-2 publishes zip on macOS.
        ARCHIVE_EXT=zip
        ;;
    Linux)
        # Linux ships as static musl, runs on any glibc / Alpine / RHEL.
        # NOTE: linux targets ship in PR-D-1.5 — until then this prints a
        # clear message instead of attempting a 404 download.
        err "Linux binaries ship in PR-D-1.5. For now: \`cargo install --git https://github.com/$REPO --branch main --bin alpha\` requires a Rust toolchain but works today."
        ;;
    MINGW*|MSYS*|CYGWIN*)
        err "Windows: use install.ps1 instead. Run in PowerShell:\n    iwr -useb https://agentprovision.com/install.ps1 | iex"
        ;;
    *) err "unsupported OS: $OS" ;;
esac

# ── tools we need ─────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || err "missing required tool: $1"; }
need curl
# Archive tool depends on platform — case below.
need mkdir
need mv
need chmod
# unzip ships with macOS by default; tar handles Linux's tar.gz once
# PR-D-1.5 lands. Pick whichever the platform ARCHIVE_EXT requires.
case "$ARCHIVE_EXT" in
    zip)    need unzip ;;
    tar.gz) need tar ;;
esac
# sha256sum on Linux, shasum -a 256 on macOS — pick whichever exists.
if command -v sha256sum >/dev/null 2>&1; then
    SHACMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    SHACMD="shasum -a 256"
else
    err "missing sha256sum / shasum"
fi

# ── resolve version → tag ─────────────────────────────────────────────────
if [ "$VERSION" = "latest" ]; then
    say "Resolving latest version from github.com/$REPO/releases/latest..."
    # The release-redirect trick: HEAD /releases/latest 302s to the actual
    # tag URL. Avoids a JSON dep (jq) and works without auth.
    TAG=$(curl -fsSL -o /dev/null -w '%{url_effective}' \
            "https://github.com/$REPO/releases/latest" \
          | sed -E 's|.*/tag/||')
    if [ -z "$TAG" ]; then err "could not resolve latest release tag"; fi
    VERSION="${TAG#cli-v}"
else
    TAG="cli-v$VERSION"
fi
say "Installing alpha $VERSION ($TRIPLE)"

# ── download ──────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

ARCHIVE="alpha-${TRIPLE}.${ARCHIVE_EXT}"
URL="https://github.com/$REPO/releases/download/$TAG/$ARCHIVE"
# PR-D-2 publishes one combined SHA256SUMS manifest per release (one
# line per archive). Half the HTTP round-trips vs. per-target sidecars,
# and survives renames.
SHASUMS_URL="https://github.com/$REPO/releases/download/$TAG/SHA256SUMS"

say "Downloading $ARCHIVE..."
curl -fsSL --retry 3 --retry-delay 2 -o "$TMP/$ARCHIVE" "$URL" \
    || err "download failed: $URL"
curl -fsSL --retry 3 --retry-delay 2 -o "$TMP/SHA256SUMS" "$SHASUMS_URL" \
    || err "SHA256SUMS download failed: $SHASUMS_URL"

# ── verify ────────────────────────────────────────────────────────────────
say "Verifying SHA256..."
# Manifest format: "<hash>  <filename>" (sha256sum-compatible).
# grep -F treats the archive name as a literal string — important because
# the filename contains a `.` that's a regex wildcard otherwise.
EXPECTED=$(grep -F "  ${ARCHIVE}" "$TMP/SHA256SUMS" | awk -v fn="$ARCHIVE" '$2 == fn {print $1}' | head -1)
if [ -z "$EXPECTED" ]; then
    err "no SHA256 line for $ARCHIVE in SHA256SUMS — release manifest incomplete?"
fi
ACTUAL=$($SHACMD "$TMP/$ARCHIVE" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    err "checksum mismatch! expected=$EXPECTED actual=$ACTUAL"
fi

# ── extract + install ─────────────────────────────────────────────────────
say "Extracting..."
mkdir -p "$TMP/extract"
case "$ARCHIVE_EXT" in
    zip)    unzip -q "$TMP/$ARCHIVE" -d "$TMP/extract" ;;
    tar.gz) tar -xzf "$TMP/$ARCHIVE" -C "$TMP/extract" ;;
esac

# The archive contains a single directory `alpha-<triple>/`.
SRC_DIR="$TMP/extract/alpha-${TRIPLE}"
if [ ! -d "$SRC_DIR" ]; then
    # Fallback: find the `alpha` binary anywhere in the extracted tree.
    SRC_DIR=$(find "$TMP/extract" -maxdepth 2 -name alpha -type f -print -quit | xargs -n1 dirname 2>/dev/null || echo "$TMP/extract")
fi

mkdir -p "$INSTALL_DIR"
mv -f "$SRC_DIR/alpha" "$INSTALL_DIR/alpha"
chmod +x "$INSTALL_DIR/alpha"
say "Installed: $INSTALL_DIR/alpha"

if [ -f "$SRC_DIR/alpha.1" ]; then
    mkdir -p "$MAN_DIR"
    cp -f "$SRC_DIR/alpha.1" "$MAN_DIR/alpha.1"
    say "Installed man page: $MAN_DIR/alpha.1"
fi

# ── PATH check ────────────────────────────────────────────────────────────
case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        say ""
        say "→ $INSTALL_DIR is not in your PATH. Add this line to your shell rc file:"
        say ""
        say "    export PATH=\"$INSTALL_DIR:\$PATH\""
        say ""
        if [ "$ADD_TO_PATH" = "1" ]; then
            for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
                [ -f "$rc" ] || continue
                if ! grep -q "$INSTALL_DIR" "$rc" 2>/dev/null; then
                    printf '\nexport PATH="%s:$PATH"\n' "$INSTALL_DIR" >> "$rc"
                    say "Appended PATH export to $rc"
                fi
            done
        fi
        ;;
esac

# ── done ──────────────────────────────────────────────────────────────────
say ""
say "alpha $VERSION ready."
say "Run:    alpha login    # to authenticate"
