"""Tests for the `claude setup-token`-based OAuth flow.

Replaces the broken `auth login --claudeai` path that stored
session-credential blobs under `credential_key='session_token'` —
those tokens were rejected by Anthropic with `401 Invalid bearer
token` because they aren't in the long-lived `sk-ant-oat01-…` shape
that `CLAUDE_CODE_OAUTH_TOKEN` requires.

Coverage:
  * `_run_login` captures the `sk-ant-oat01-…` token from
    subprocess stdout and persists it to the vault under
    `credential_key='session_token'`.
  * Wrong-shape stdout (garbage, no token, truncated prefix) is
    rejected — no row is stored and a clear error surfaces in
    `state.error`.
  * `_persist_credentials` invokes the post-login probe; a probe
    failure refuses persist and surfaces an error.
  * Migration `135_revoke_stale_claude_session_tokens.sql` flips every
    active `claude_code.session_token` row to `status='revoked'` and
    is idempotent (second apply is a no-op).

Design: docs/plans/2026-05-16-oauth-reconnect-token-format-mismatch.md
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from app.api.v1 import claude_auth as ca


# ── Helpers ───────────────────────────────────────────────────────────────

# A representative long-lived OAuth token. Matches the
# `sk-ant-oat01-…` shape Anthropic emits from `claude setup-token`.
# Padded to >20 chars after the prefix so the regex accepts it.
_GOOD_TOKEN = "sk-ant-oat01-" + "A" * 60


def _drain_state(tenant_id: str = "tenant-x") -> ca.ClaudeLoginState:
    """Build a `ClaudeLoginState` with the buffer/process slots that
    `_run_login`'s post-wait branch reads from."""
    return ca.ClaudeLoginState(
        login_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        status="submitting",
    )


# ── _extract_oat01_token: pure scanner ────────────────────────────────────

def test_extract_oat01_token_finds_token_in_stdout():
    """The scanner must locate the token line `claude setup-token`
    emits near the end of its stdout. We mix in human-friendly
    preamble + ANSI-stripped fragments to mirror real output."""
    stdout = (
        "Opening browser at https://claude.com/oauth/authorize?code=ABC\n"
        "Paste code from browser > XYZ123\n"
        f"{_GOOD_TOKEN}\n"
        "Token printed above. Set as CLAUDE_CODE_OAUTH_TOKEN env var.\n"
    )
    assert ca._extract_oat01_token(stdout) == _GOOD_TOKEN


def test_extract_oat01_token_returns_none_on_garbage():
    """No token-shaped substring → None, not an empty string. The
    caller (`_run_login`) treats None as a hard failure rather than
    falling through to a salvage path."""
    assert ca._extract_oat01_token("hello world\nno token here\n") is None
    # Prefix without enough trailing chars must NOT match — we don't
    # want to accept truncated tokens.
    assert ca._extract_oat01_token("sk-ant-oat01-short") is None
    assert ca._extract_oat01_token("") is None


# ── _persist_credentials: storage + probe gate ────────────────────────────

def test_setup_token_login_captures_oat01_and_stores_under_session_token(monkeypatch):
    """The happy path: a valid `sk-ant-oat01-…` token on the state
    lands in the vault under `credential_key='session_token'` and
    `credential_type='oauth_token'`. Executor contract preserved."""
    state = _drain_state("11111111-1111-1111-1111-111111111111")
    state.captured_token = _GOOD_TOKEN

    # Probe stub: succeed without spawning a real subprocess.
    monkeypatch.setattr(ca, "_probe_oauth_token", lambda token: True)

    captured = []

    def fake_store_credential(db, **kw):
        captured.append(kw)

    monkeypatch.setattr(ca, "store_credential", fake_store_credential)

    # Self-chaining db mock — query().filter().first() returns a
    # pre-built IntegrationConfig so we don't go through the
    # "create new" branch.
    chain = MagicMock()
    chain.filter.return_value = chain
    cfg = MagicMock()
    cfg.id = uuid.uuid4()
    cfg.enabled = True
    chain.first.return_value = cfg
    chain.update.return_value = None
    db = MagicMock()
    db.query.return_value = chain

    monkeypatch.setattr(ca, "SessionLocal", lambda: db)

    mgr = ca.ClaudeAuthManager()
    mgr._persist_credentials(state)

    assert len(captured) == 1
    kw = captured[0]
    assert kw["credential_key"] == "session_token"
    assert kw["credential_type"] == "oauth_token"
    # The vault must receive the token verbatim — not wrapped in
    # JSON, not concatenated, not transformed. That was the entire
    # bug class the rewrite eliminates.
    assert kw["plaintext_value"] == _GOOD_TOKEN


def test_setup_token_login_rejects_wrong_shape(monkeypatch):
    """A non-`sk-ant-oat01-` token must NOT reach the vault. Surface
    a RuntimeError so `_run_login` can paint `state.error` for the
    UI."""
    state = _drain_state()
    state.captured_token = "not-a-real-token-blob"

    monkeypatch.setattr(ca, "_probe_oauth_token", lambda token: True)

    calls = []
    monkeypatch.setattr(ca, "store_credential", lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(ca, "SessionLocal", lambda: MagicMock())

    mgr = ca.ClaudeAuthManager()
    with pytest.raises(RuntimeError) as exc:
        mgr._persist_credentials(state)
    assert "sk-ant-oat01" in str(exc.value)
    # Critically: zero vault writes on shape failure.
    assert calls == []


def test_setup_token_login_rejects_empty_token(monkeypatch):
    """Empty captured_token (CLI exited 0 but printed nothing
    token-shaped) must also fail-closed."""
    state = _drain_state()
    state.captured_token = ""

    monkeypatch.setattr(ca, "_probe_oauth_token", lambda token: True)
    calls = []
    monkeypatch.setattr(ca, "store_credential", lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(ca, "SessionLocal", lambda: MagicMock())

    mgr = ca.ClaudeAuthManager()
    with pytest.raises(RuntimeError):
        mgr._persist_credentials(state)
    assert calls == []


def test_setup_token_probe_validates_token(monkeypatch):
    """Probe-failure path: shape is correct, but the probe subprocess
    rejected the token. Persist is refused, vault stays untouched,
    error surfaces to caller."""
    state = _drain_state()
    state.captured_token = _GOOD_TOKEN

    # Probe says "no" — token did not pass `claude --version` exec.
    monkeypatch.setattr(ca, "_probe_oauth_token", lambda token: False)

    calls = []
    monkeypatch.setattr(ca, "store_credential", lambda db, **kw: calls.append(kw))
    monkeypatch.setattr(ca, "SessionLocal", lambda: MagicMock())

    mgr = ca.ClaudeAuthManager()
    with pytest.raises(RuntimeError) as exc:
        mgr._persist_credentials(state)
    assert "probe" in str(exc.value).lower() or "rejected" in str(exc.value).lower()
    assert calls == [], "Probe failure must NOT write to the vault"


# ── _probe_oauth_token: subprocess behaviour ──────────────────────────────

def test_probe_oauth_token_passes_on_zero_exit(monkeypatch):
    """A clean `claude --version` exit means the CLI accepted the
    token's on-disk shape."""
    fake_result = MagicMock()
    fake_result.returncode = 0

    captured_env = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return fake_result

    monkeypatch.setattr(ca.subprocess, "run", fake_run)
    assert ca._probe_oauth_token(_GOOD_TOKEN) is True
    # The probe MUST set CLAUDE_CODE_OAUTH_TOKEN and MUST strip any
    # inherited ANTHROPIC_API_KEY — otherwise the CLI's auth
    # precedence would short-circuit to the API key and the probe
    # wouldn't actually exercise the OAuth path. This is the same
    # rationale as PR #531 on the executor side.
    assert captured_env.get("CLAUDE_CODE_OAUTH_TOKEN") == _GOOD_TOKEN
    assert "ANTHROPIC_API_KEY" not in captured_env


def test_probe_oauth_token_fails_on_nonzero_exit(monkeypatch):
    """CLI exited non-zero → probe reports failure → caller refuses
    to persist."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **kw: fake_result)
    assert ca._probe_oauth_token(_GOOD_TOKEN) is False


def test_probe_oauth_token_recovers_when_cli_missing(monkeypatch):
    """If the api container has no `claude` binary, probe returns True
    (recoverable) — the code-worker container will probe properly at
    executor time. We don't want this edge to block the entire login
    flow during dev/test."""

    def raise_fnf(*a, **kw):
        raise FileNotFoundError("claude not on PATH")

    monkeypatch.setattr(ca.subprocess, "run", raise_fnf)
    assert ca._probe_oauth_token(_GOOD_TOKEN) is True


# ── Migration 135: revoke stale session_token rows ────────────────────────

# Path resolved at import time, asserted to exist so a missing-file
# regression surfaces as an immediate failure instead of a confusing
# psycopg2 error mid-test.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "135_revoke_stale_claude_session_tokens.sql"
)


def test_migration_135_file_exists():
    assert _MIGRATION_PATH.exists(), f"Missing migration: {_MIGRATION_PATH}"


def test_migration_135_targets_claude_session_tokens_only():
    """Static analysis of the migration SQL — it MUST scope the
    revoke to `claude_code` integration + `session_token` key. A
    regression that dropped the integration filter would revoke
    every `session_token` row in the vault (across all
    integrations) and lock every tenant out at once."""
    sql = _MIGRATION_PATH.read_text()
    assert "credential_key = 'session_token'" in sql
    assert "integration_name = 'claude_code'" in sql
    # Must NOT revoke api_key rows — the Anthropic-Console fast-path
    # is unaffected by this bug and pulling that out from under
    # users on Console billing would be a UX disaster.
    assert "credential_key = 'api_key'" not in sql


def test_migration_135_is_idempotent_shape():
    """Idempotence guard: the migration MUST filter on
    `status = 'active'` so a second apply matches zero rows."""
    sql = _MIGRATION_PATH.read_text()
    assert re.search(r"status\s*=\s*'active'", sql), (
        "Migration must filter on status='active' to be idempotent"
    )


def test_migration_revokes_existing_session_tokens(monkeypatch):
    """Apply the migration against a sqlite in-memory DB pre-seeded
    with two `session_token` rows and one `api_key` row. After
    apply: both session_token rows show `status='revoked'`, the
    api_key row is untouched. Second apply is a no-op (idempotent).

    Why sqlite: pytest doesn't get a Postgres backend in this
    suite; we exercise the SQL shape (UPDATE … WHERE) and the
    integration_configs join. Postgres-specific bits (`NOW()`,
    `BEGIN`/`COMMIT`) are translated by the test harness below.
    """
    sqlite3 = pytest.importorskip("sqlite3")

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE integration_configs (
            id TEXT PRIMARY KEY,
            integration_name TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE integration_credentials (
            id TEXT PRIMARY KEY,
            integration_config_id TEXT NOT NULL,
            credential_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            updated_at TEXT
        )
        """
    )
    cfg_claude = str(uuid.uuid4())
    cfg_other = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO integration_configs (id, integration_name) VALUES (?, ?)",
        (cfg_claude, "claude_code"),
    )
    cur.execute(
        "INSERT INTO integration_configs (id, integration_name) VALUES (?, ?)",
        (cfg_other, "gemini_cli"),
    )
    # Two stale claude session_token rows + one gemini api_key row
    # that must NOT be revoked.
    cur.execute(
        "INSERT INTO integration_credentials (id, integration_config_id, credential_key, status) "
        "VALUES (?, ?, 'session_token', 'active')",
        (str(uuid.uuid4()), cfg_claude),
    )
    cur.execute(
        "INSERT INTO integration_credentials (id, integration_config_id, credential_key, status) "
        "VALUES (?, ?, 'session_token', 'active')",
        (str(uuid.uuid4()), cfg_claude),
    )
    cur.execute(
        "INSERT INTO integration_credentials (id, integration_config_id, credential_key, status) "
        "VALUES (?, ?, 'api_key', 'active')",
        (str(uuid.uuid4()), cfg_other),
    )
    conn.commit()

    # Translate Postgres-isms to sqlite-isms. The actual SQL shape
    # (UPDATE … WHERE credential_key + status + IN subselect) is
    # what the test is checking — `NOW()` and explicit BEGIN/COMMIT
    # are decorations not under test here.
    raw_sql = _MIGRATION_PATH.read_text()
    portable_sql = (
        raw_sql.replace("NOW()", "'2026-05-16T00:00:00Z'")
               .replace("BEGIN;", "")
               .replace("COMMIT;", "")
    )

    # First apply: must revoke the two claude rows.
    cur.executescript(portable_sql)
    conn.commit()

    rows = cur.execute(
        "SELECT credential_key, status, integration_config_id FROM integration_credentials"
    ).fetchall()
    by_key = {(k, cfg): s for (k, s, cfg) in rows}
    # Both claude session_token rows revoked.
    for (k, _s, cfg) in rows:
        if k == "session_token" and cfg == cfg_claude:
            assert _s == "revoked", "Claude session_token must be revoked"
        elif k == "api_key":
            assert _s == "active", "api_key on a different integration must be untouched"

    # No new rows created.
    assert len(rows) == 3

    # Second apply: idempotent — must match zero rows, zero
    # state change.
    snapshot_before = sorted(rows)
    cur.executescript(portable_sql)
    conn.commit()
    rows2 = cur.execute(
        "SELECT credential_key, status, integration_config_id FROM integration_credentials"
    ).fetchall()
    assert sorted(rows2) == snapshot_before, (
        "Migration is NOT idempotent — second apply changed state"
    )
    conn.close()


# ── _run_login: spawn cmd is `claude setup-token` ─────────────────────────


def test_run_login_spawns_setup_token_not_auth_login(monkeypatch):
    """Lock in the spawn command. A regression that flips back to
    `claude auth login --claudeai` would re-introduce the entire bug
    class — this assertion fails first to catch that immediately.

    We don't drive the full state machine here; we only need to
    inspect the `subprocess.Popen` invocation. The thread is short-
    circuited by injecting a Popen that fails fast (FileNotFoundError
    on stdin write → state moves to 'failed' deterministically).
    """
    captured_cmd = {}

    def fake_popen(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        # Raise FileNotFoundError after capturing the cmd so the
        # thread bails immediately without polling subprocess state.
        raise FileNotFoundError("synthetic — abort after cmd capture")

    monkeypatch.setattr(ca.subprocess, "Popen", fake_popen)

    state = ca.ClaudeLoginState(
        login_id="x",
        tenant_id="t",
        claude_home="/tmp/nonexistent",
    )
    mgr = ca.ClaudeAuthManager()
    mgr._run_login(state)

    assert captured_cmd.get("cmd") == ["claude", "setup-token"], (
        f"Wrong spawn cmd: {captured_cmd.get('cmd')!r} — "
        "must be `claude setup-token` to produce a valid "
        "CLAUDE_CODE_OAUTH_TOKEN-shaped artefact"
    )
    # Subprocess spawn failure → state must be terminal 'failed'.
    assert state.status == "failed"
