# install.ps1 — PowerShell installer for the `agentprovision` CLI on Windows.
#
# Usage:
#   iwr -useb https://agentprovision.com/install.ps1 | iex
#
# Pin a version:
#   $env:AGENTPROVISION_VERSION="0.1.0"; iwr -useb https://agentprovision.com/install.ps1 | iex
#
# What it does:
#   1. Refuses to run elevated (no admin needed; installs into %USERPROFILE%).
#   2. Detects arch (AMD64 → x86_64-pc-windows-msvc; ARM64 deferred to PR-D-1.5).
#   3. Resolves a concrete version (latest stable, or AGENTPROVISION_VERSION).
#   4. Downloads the matching .zip release archive + its SHA256 sidecar.
#   5. Verifies SHA256.
#   6. Extracts to a temp dir; moves agentprovision.exe →
#      $env:USERPROFILE\.agentprovision\bin.
#   7. Updates User-scope PATH (no UAC, no admin) so new terminals find it.
#   8. Cleans up.
#
# Idempotent: re-running upgrades cleanly. Use `agentprovision upgrade`
# instead once you have an install.

[CmdletBinding()]
param(
    [string]$Version = $env:AGENTPROVISION_VERSION,
    [string]$InstallDir = (Join-Path $env:USERPROFILE ".agentprovision\bin"),
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Repo = "nomad3/servicetsunami-agents"
if (-not $Version) { $Version = "latest" }

function Say { param($msg) if (-not $Quiet) { Write-Host $msg } }
function Fail { param($msg) Write-Error "install.ps1: $msg"; exit 1 }

# ── refuse elevated session ───────────────────────────────────────────────
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "do not run elevated. agentprovision installs into `$env:USERPROFILE\.agentprovision\bin (no admin needed)."
}

# ── detect arch ───────────────────────────────────────────────────────────
$arch = $env:PROCESSOR_ARCHITECTURE
switch ($arch) {
    "AMD64" { $triple = "x86_64-pc-windows-msvc" }
    "ARM64" {
        Fail "Windows ARM64 binaries ship in PR-D-1.5. For now use x64 binary via Windows on ARM emulation, or build from source."
    }
    default { Fail "unsupported architecture: $arch" }
}

# ── resolve version → tag ─────────────────────────────────────────────────
if ($Version -eq "latest") {
    Say "Resolving latest version from github.com/$Repo/releases/latest..."
    # 302 redirect from /releases/latest → /tag/<tag>. -MaximumRedirection 0
    # forces a single hop so we can read the Location header.
    try {
        $resp = Invoke-WebRequest -Uri "https://github.com/$Repo/releases/latest" `
                                  -MaximumRedirection 0 `
                                  -ErrorAction SilentlyContinue
    } catch {
        # PowerShell throws on 302; the exception still has the Response.
        $resp = $_.Exception.Response
    }
    if ($resp.Headers.Location) {
        $loc = if ($resp.Headers.Location -is [Array]) { $resp.Headers.Location[0] } else { $resp.Headers.Location }
    } else {
        $loc = $resp.Headers["Location"]
    }
    if (-not $loc) { Fail "could not resolve latest release tag" }
    $tag = ($loc -split "/tag/")[-1]
    $Version = $tag -replace "^cli-v", ""
} else {
    $tag = "cli-v$Version"
}
Say "Installing agentprovision $Version ($triple)"

# ── download ──────────────────────────────────────────────────────────────
$tmp = Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    $archiveName = "agentprovision-$triple.zip"
    $url = "https://github.com/$Repo/releases/download/$tag/$archiveName"
    $shaUrl = "https://github.com/$Repo/releases/download/$tag/$archiveName.sha256"
    $archivePath = Join-Path $tmp $archiveName
    $shaPath = Join-Path $tmp "$archiveName.sha256"

    Say "Downloading $archiveName..."
    Invoke-WebRequest -Uri $url -OutFile $archivePath -UseBasicParsing
    Invoke-WebRequest -Uri $shaUrl -OutFile $shaPath -UseBasicParsing

    # ── verify ────────────────────────────────────────────────────────────
    Say "Verifying SHA256..."
    $expected = ((Get-Content $shaPath -Raw).Trim() -split "\s+")[0].ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 $archivePath).Hash.ToLower()
    if ($expected -ne $actual) {
        Fail "checksum mismatch! expected=$expected actual=$actual"
    }

    # ── extract + install ─────────────────────────────────────────────────
    Say "Extracting..."
    $extractDir = Join-Path $tmp "extract"
    Expand-Archive -Path $archivePath -DestinationPath $extractDir -Force

    # Find the agentprovision.exe in the extracted tree.
    $exe = Get-ChildItem -Path $extractDir -Recurse -Filter "agentprovision.exe" |
           Select-Object -First 1
    if (-not $exe) { Fail "agentprovision.exe not found in archive" }

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    }
    Copy-Item -Force $exe.FullName (Join-Path $InstallDir "agentprovision.exe")
    Say "Installed: $InstallDir\agentprovision.exe"

    # ── PATH (User scope — no UAC) ────────────────────────────────────────
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $pathEntries = if ($userPath) { $userPath -split ";" } else { @() }
    if ($pathEntries -notcontains $InstallDir) {
        $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Say ""
        Say "→ Added $InstallDir to your User PATH."
        Say "  Open a new PowerShell window for the change to take effect."
    }

    Say ""
    Say "✓ agentprovision $Version ready."
    Say "Run:    agentprovision login    # to authenticate"
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
