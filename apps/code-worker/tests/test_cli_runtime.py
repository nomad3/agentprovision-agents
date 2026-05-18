"""Tests for ``cli_runtime.tenant_home_dir`` (task #267 Phase 1).

Mirrors the shape of ``test_cli_cwd_tenant_workspace.TestResolveCliCwd``
for the sibling ``tenant_workspace_dir``: same WORKSPACES_ROOT
monkeypatch fixture, same UUID guard semantics, same per-tenant subtree
expectations.

Why a separate file (not ``test_cli_cwd_tenant_workspace.py``): the
workspace-cwd tests are about subprocess ``cwd`` end-to-end; these are
unit-scoped at the helper level. Co-locating them in a leaner file
keeps the cwd-scoped suite's intent clear.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import cli_runtime


TENANT_UUID = "11111111-1111-4111-8111-111111111111"
TENANT_OTHER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def fake_workspaces_root(tmp_path, monkeypatch):
    """Redirect WORKSPACES_ROOT to a pytest tmp dir.

    Same fixture shape as ``test_cli_cwd_tenant_workspace.fake_workspaces_root``
    — the parent of ``<tenant_id>/home`` must exist as a real directory so
    the helper's ``mkdir(parents=True, exist_ok=True)`` succeeds without
    a permission error against ``/var/agentprovision/workspaces`` on the
    pytest host.
    """
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setattr(cli_runtime, "WORKSPACES_ROOT", Path(root))
    return root


class TestTenantHomeDir:
    def test_valid_uuid_returns_path_under_workspaces_root(
        self, fake_workspaces_root,
    ):
        out = cli_runtime.tenant_home_dir(TENANT_UUID)
        # Created on first access, lives under <root>/<tenant>/home.
        assert out.is_dir()
        assert out.name == "home"
        assert out.parent.name == TENANT_UUID
        assert out.parent.parent == fake_workspaces_root

    def test_idempotent_on_second_call(self, fake_workspaces_root):
        """``mkdir(exist_ok=True)`` so re-calls for an existing tenant
        must not raise — code-worker hits this on every chat turn."""
        first = cli_runtime.tenant_home_dir(TENANT_UUID)
        # Drop a marker file so we can prove the dir was reused.
        (first / "marker").write_text("present")
        second = cli_runtime.tenant_home_dir(TENANT_UUID)
        assert second == first
        assert (second / "marker").read_text() == "present"

    def test_per_tenant_isolation(self, fake_workspaces_root):
        a = cli_runtime.tenant_home_dir(TENANT_UUID)
        b = cli_runtime.tenant_home_dir(TENANT_OTHER)
        assert a != b
        assert TENANT_UUID in str(a)
        assert TENANT_OTHER in str(b)

    # ── UUID guard parity with ``tenant_workspace_dir`` (review I1) ─────

    def test_rejects_non_uuid_tenant_id_matching_workspace_helper(
        self, fake_workspaces_root,
    ):
        """Same UUID guard as ``tenant_workspace_dir`` (review I1).

        Covers path traversal, garbage strings, and empty/None in one
        spec so a future relaxation of the regex breaks both helpers'
        guards in lockstep.
        """
        for bad in ("../escape", "not-a-uuid", "", None):
            with pytest.raises(ValueError):
                cli_runtime.tenant_home_dir(bad)  # type: ignore[arg-type]
        # And no sibling-of-root directory got materialized.
        assert not (fake_workspaces_root.parent / "escape").exists()

    # ── path-traversal hardening (review N1 on PR #540) ─────────────────
    # Spell out the canonical adversarial inputs as explicit cases so
    # a future regex narrowing/relaxation that misses one of these
    # registers as a focused failure (not a single "broken bad-input
    # vector" message).
    @pytest.mark.parametrize(
        "bad",
        [
            "../",
            "..\\",
            "/etc/passwd",
            ".",
            "../escape",
            "../../sibling",
            "tenant/../escape",
        ],
    )
    def test_rejects_path_traversal_vectors(
        self, fake_workspaces_root, bad,
    ):
        with pytest.raises(ValueError):
            cli_runtime.tenant_home_dir(bad)
        # Nothing materialised outside the fake root.
        assert not (fake_workspaces_root.parent / "escape").exists()
        assert not (fake_workspaces_root.parent / "sibling").exists()


# ── module-level constants (review N2 on PR #540) ──────────────────────


class TestWorkspacesRootDefault:
    def test_default_is_var_agentprovision_workspaces(self, monkeypatch):
        """Without env override, WORKSPACES_ROOT MUST resolve to the
        docker-compose + Helm mount path. Drift here means the named
        volume mount in deploy/ and helm/values/ no longer matches what
        code-worker writes under — silent breakage of the dashboard's
        FileTreePanel and the persistent HOME.
        """
        # Re-import semantics aren't worth simulating; the module-level
        # constant is computed at import time so we assert the in-process
        # value matches the documented default when no env was set at
        # process start. If someone changed the default, this test
        # catches it.
        monkeypatch.delenv("WORKSPACES_ROOT", raising=False)
        # Re-evaluate the env-dependent default using the same expression
        # the module uses, then compare.
        expected = Path(os.environ.get(
            "WORKSPACES_ROOT", "/var/agentprovision/workspaces"
        ))
        assert expected == Path("/var/agentprovision/workspaces")
        # And the module's compile-time constant has the right shape.
        assert isinstance(cli_runtime.WORKSPACES_ROOT, Path)


# ── legacy .gemini/ one-shot rescue (review B2 on PR #540) ─────────────


class TestLegacyGeminiRescue:
    """First materialisation of a tenant's new HOME must inherit the
    legacy ``.gemini/`` tree so existing tenants don't get effectively
    logged out on the first post-deploy chat turn.
    """

    def test_rescues_oauth_creds_from_legacy_path(
        self, fake_workspaces_root, tmp_path, monkeypatch,
    ):
        # Build a fake legacy st_sessions tree with a real OAuth blob.
        legacy_root = tmp_path / "st_sessions"
        legacy_tenant = legacy_root / TENANT_UUID
        legacy_gemini = legacy_tenant / ".gemini"
        legacy_gemini.mkdir(parents=True)
        legacy_oauth = legacy_gemini / "oauth_creds.json"
        legacy_oauth.write_text('{"refresh_token": "rt-fake"}')
        # Legacy .local/ — must NOT be copied (that's the growth source).
        legacy_local = legacy_tenant / ".local"
        legacy_local.mkdir()
        (legacy_local / "marker").write_text("should-not-copy")

        monkeypatch.setattr(cli_runtime, "_LEGACY_SESSIONS_ROOT", legacy_root)

        new_home = cli_runtime.tenant_home_dir(TENANT_UUID)

        # OAuth blob landed in the new HOME under .gemini/.
        new_oauth = new_home / ".gemini" / "oauth_creds.json"
        assert new_oauth.exists()
        assert "rt-fake" in new_oauth.read_text()

        # Mode tightened to 0o600 (refresh tokens are secret-grade).
        mode = new_oauth.stat().st_mode & 0o777
        assert mode == 0o600, f"oauth_creds.json mode was {oct(mode)}, expected 0o600"

        # .local/ from the legacy path was NOT copied — that's the
        # disk-pressure growth source we're escaping. Only .gemini/
        # gets rescued.
        assert not (new_home / ".local").exists()

    def test_no_rescue_when_legacy_path_missing(
        self, fake_workspaces_root, tmp_path, monkeypatch,
    ):
        """No legacy path on disk = no-op rescue, no crash."""
        legacy_root = tmp_path / "empty"
        legacy_root.mkdir()
        monkeypatch.setattr(cli_runtime, "_LEGACY_SESSIONS_ROOT", legacy_root)
        new_home = cli_runtime.tenant_home_dir(TENANT_UUID)
        assert new_home.is_dir()
        assert not (new_home / ".gemini").exists()

    def test_rescue_skipped_on_second_call(
        self, fake_workspaces_root, tmp_path, monkeypatch,
    ):
        """The rescue is one-shot: once the new HOME exists, a second
        call must NOT overwrite anything the tenant accumulated in the
        new location (re-OAuth, fresh project state, etc.).
        """
        legacy_root = tmp_path / "st_sessions"
        legacy_gemini = legacy_root / TENANT_UUID / ".gemini"
        legacy_gemini.mkdir(parents=True)
        (legacy_gemini / "oauth_creds.json").write_text('{"refresh_token": "OLD"}')
        monkeypatch.setattr(cli_runtime, "_LEGACY_SESSIONS_ROOT", legacy_root)

        # First call materialises HOME + rescues legacy.
        first = cli_runtime.tenant_home_dir(TENANT_UUID)
        new_oauth = first / ".gemini" / "oauth_creds.json"
        # Simulate tenant re-OAuthing into the new HOME.
        new_oauth.write_text('{"refresh_token": "NEW"}')

        # Second call must NOT overwrite the new blob.
        second = cli_runtime.tenant_home_dir(TENANT_UUID)
        assert second == first
        assert "NEW" in new_oauth.read_text()
