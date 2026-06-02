"""WhatsApp session-durability tests (design 2026-06-02 + Codex-5.5 review).

Covers the two contracts the fix turns on:

  C1/C2 — `_save_session_to_db` NEVER overwrites a known-good copy with an
          unvalidated blob (checkpoint failure or validation failure aborts
          the write before the DB is even opened — the inverse of the old
          "corruption amplifier").
  recover-never-QR — `_restore_session_from_db` skips a corrupt current blob
          and self-heals from the newest validated backup; a QR is reached
          only when every copy is unusable.
  plus    `_validate_sqlite_bytes` (the gate), and a regression guard that
          recovery code never calls the destructive `start_pairing(force=...)`.

These are fast/pure: no Postgres, no neonize. The service is instantiated
with `_ensure_neonize` patched out; DB access is faked because the abort
paths return before any DB call and the restore candidate list is assembled
from injected fakes.
"""
import asyncio
import gzip
import inspect
import os
import sqlite3
import tempfile
import types

import pytest

import app.services.whatsapp_service as wa_mod


# ── helpers ──────────────────────────────────────────────────────────────
def _make_session_db(path, *, with_device=True, with_row=True):
    """Create a neonize-shaped SQLite file (whatsmeow_device table)."""
    conn = sqlite3.connect(path)
    try:
        if with_device:
            conn.execute(
                "CREATE TABLE whatsmeow_device (jid TEXT PRIMARY KEY, registration_id INTEGER)"
            )
            if with_row:
                conn.execute(
                    "INSERT INTO whatsmeow_device (jid, registration_id) VALUES "
                    "('123@s.whatsapp.net', 42)"
                )
        else:
            conn.execute("CREATE TABLE misc (k TEXT)")
            conn.execute("INSERT INTO misc (k) VALUES ('x')")
        conn.commit()
    finally:
        conn.close()
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture()
def service(monkeypatch):
    monkeypatch.setattr(wa_mod, "_ensure_neonize", lambda: None)
    return wa_mod.WhatsAppService(db_url="sqlite://")


@pytest.fixture()
def tmp_session(tmp_path, service, monkeypatch):
    """Point _client_name at a temp file path for one account."""
    path = str(tmp_path / "wa_test.db")
    monkeypatch.setattr(service, "_client_name", lambda tid, aid="default": path)
    return path


# ── _validate_sqlite_bytes (the gate) ──────────────────────────────────────
class TestValidate:
    def test_valid_session_with_device_row_passes(self, service, tmp_path):
        raw = _make_session_db(str(tmp_path / "a.db"))
        ok, reason = service._validate_sqlite_bytes(raw)
        assert ok is True
        assert reason == "ok"

    def test_device_table_present_but_empty_fails(self, service, tmp_path):
        raw = _make_session_db(str(tmp_path / "b.db"), with_row=False)
        ok, reason = service._validate_sqlite_bytes(raw)
        assert ok is False
        assert "no auth keys" in reason

    def test_garbage_bytes_fail_bad_magic(self, service):
        ok, reason = service._validate_sqlite_bytes(b"this is not a database")
        assert ok is False
        assert "bad magic" in reason

    def test_truncated_sqlite_fails(self, service, tmp_path):
        raw = _make_session_db(str(tmp_path / "c.db"))
        # Corrupt the page data but keep the magic header so it reaches
        # integrity_check / open and fails there, not on magic.
        corrupt = raw[:32] + b"\x00" * (len(raw) - 32)
        ok, _ = service._validate_sqlite_bytes(corrupt)
        assert ok is False

    def test_empty_bytes_fail(self, service):
        ok, _ = service._validate_sqlite_bytes(b"")
        assert ok is False

    def test_no_device_table_rejected(self, service, tmp_path):
        # A device-less blob (integrity ok, but no whatsmeow device table) is a
        # HARD FAIL on validation — it must never become a known-good copy
        # (review C2-VALIDATE-FALSE-POSITIVE). Better to keep the last good one.
        raw = _make_session_db(str(tmp_path / "d.db"), with_device=False)
        ok, reason = service._validate_sqlite_bytes(raw)
        assert ok is False
        assert "no device table" in reason


# ── _save_session_to_db: never overwrite known-good (C2) ───────────────────
class TestSaveNeverOverwrites:
    def test_checkpoint_failure_aborts_before_db(self, service, tmp_session, monkeypatch):
        _make_session_db(tmp_session)  # a real, valid file exists

        # _get_db must NEVER be reached on a checkpoint failure.
        def _boom():
            raise AssertionError("_get_db called — would have overwritten known-good")
        monkeypatch.setattr(service, "_get_db", _boom)

        # Force the checkpoint connect to fail (DB locked / mid-write). The
        # function does a local `import sqlite3`, so patch the stdlib module
        # (after _make_session_db above, which needs the real connect).
        def _connect_fail(*a, **k):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(sqlite3, "connect", _connect_fail)

        result = service._save_session_to_db("tenant-abc", "default")
        assert result is False

    def test_validation_failure_aborts_before_db(self, service, tmp_session, monkeypatch):
        _make_session_db(tmp_session)  # valid file → checkpoint succeeds

        def _boom():
            raise AssertionError("_get_db called — would have overwritten known-good")
        monkeypatch.setattr(service, "_get_db", _boom)

        # Simulate a validation failure (e.g. disconnect-timeout mid-write).
        monkeypatch.setattr(service, "_validate_sqlite_bytes", lambda raw: (False, "forced"))

        result = service._save_session_to_db("tenant-abc", "default")
        assert result is False

    def test_missing_file_returns_false(self, service, tmp_session, monkeypatch):
        # No file created at tmp_session.
        def _boom():
            raise AssertionError("_get_db called for a missing session file")
        monkeypatch.setattr(service, "_get_db", _boom)
        assert service._save_session_to_db("tenant-abc", "default") is False

    def test_read_failure_aborts_before_db(self, service, tmp_session, monkeypatch):
        _make_session_db(tmp_session)  # valid file → checkpoint succeeds

        def _boom():
            raise AssertionError("_get_db called after a read failure — would overwrite")
        monkeypatch.setattr(service, "_get_db", _boom)
        # Make the post-checkpoint file read raise.
        import builtins
        real_open = builtins.open

        def _open(path, *a, **k):
            if str(path) == tmp_session and (a and "b" in a[0]):
                raise OSError("read failed")
            return real_open(path, *a, **k)
        monkeypatch.setattr(builtins, "open", _open)
        assert service._save_session_to_db("tenant-abc", "default") is False


# ── _restore_session_from_db: multi-tier, recover-never-QR ─────────────────
class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, backups):
        self._backups = backups
        self.committed = False

    def query(self, *a, **k):
        return _FakeQuery(self._backups)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _backup(blob):
    return types.SimpleNamespace(blob=blob, validation_status="ok")


class TestRestoreMultiTier:
    def test_corrupt_current_falls_back_to_valid_backup(self, service, tmp_session, monkeypatch, tmp_path):
        good_raw = _make_session_db(str(tmp_path / "good.db"))
        good_blob = gzip.compress(good_raw)
        corrupt_blob = gzip.compress(b"not a sqlite file at all")

        acct = types.SimpleNamespace(tenant_id="t", session_blob=corrupt_blob)
        fake_db = _FakeSession([_backup(good_blob)])
        monkeypatch.setattr(service, "_get_db", lambda: fake_db)
        monkeypatch.setattr(service, "_get_or_create_account", lambda db, tid, aid: acct)

        ok = service._restore_session_from_db("tenant-abc", "default")
        assert ok is True
        # The VALID backup bytes were written to disk (not the corrupt current).
        assert os.path.exists(tmp_session)
        with open(tmp_session, "rb") as f:
            assert f.read() == good_raw
        # Self-heal: corrupt current was promoted to the recovered good blob.
        assert acct.session_blob == good_blob
        assert fake_db.committed is True

    def test_valid_current_used_directly(self, service, tmp_session, monkeypatch, tmp_path):
        good_raw = _make_session_db(str(tmp_path / "good2.db"))
        good_blob = gzip.compress(good_raw)
        acct = types.SimpleNamespace(tenant_id="t", session_blob=good_blob)
        fake_db = _FakeSession([])
        monkeypatch.setattr(service, "_get_db", lambda: fake_db)
        monkeypatch.setattr(service, "_get_or_create_account", lambda db, tid, aid: acct)

        ok = service._restore_session_from_db("tenant-abc", "default")
        assert ok is True
        with open(tmp_session, "rb") as f:
            assert f.read() == good_raw

    def test_all_copies_corrupt_returns_false_no_write(self, service, tmp_session, monkeypatch):
        bad = gzip.compress(b"garbage")
        acct = types.SimpleNamespace(tenant_id="t", session_blob=bad)
        fake_db = _FakeSession([_backup(gzip.compress(b"also garbage"))])
        monkeypatch.setattr(service, "_get_db", lambda: fake_db)
        monkeypatch.setattr(service, "_get_or_create_account", lambda db, tid, aid: acct)

        ok = service._restore_session_from_db("tenant-abc", "default")
        assert ok is False
        # Nothing valid → no file written (would otherwise corrupt on-disk state).
        assert not os.path.exists(tmp_session)

    def test_no_copies_returns_false(self, service, tmp_session, monkeypatch):
        acct = types.SimpleNamespace(tenant_id="t", session_blob=None)
        fake_db = _FakeSession([])
        monkeypatch.setattr(service, "_get_db", lambda: fake_db)
        monkeypatch.setattr(service, "_get_or_create_account", lambda db, tid, aid: acct)
        assert service._restore_session_from_db("tenant-abc", "default") is False

    def test_all_copies_corrupt_normalizes_preexisting_on_disk(self, service, tmp_session, monkeypatch):
        # A torn .db left on persistent storage by a prior SIGKILL-mid-write
        # must be cleared (stashed) when every durable copy is unusable, so
        # neonize starts from a deterministic clean slate (review MTR-3).
        with open(tmp_session, "wb") as f:
            f.write(b"torn corrupt sqlite bytes")
        with open(tmp_session + "-wal", "wb") as f:
            f.write(b"stale wal")
        acct = types.SimpleNamespace(tenant_id="t", session_blob=gzip.compress(b"garbage"))
        fake_db = _FakeSession([])
        monkeypatch.setattr(service, "_get_db", lambda: fake_db)
        monkeypatch.setattr(service, "_get_or_create_account", lambda db, tid, aid: acct)

        ok = service._restore_session_from_db("tenant-abc", "default")
        assert ok is False
        # On-disk .db stashed to .corrupt-backup; .db + -wal removed.
        assert not os.path.exists(tmp_session)
        assert not os.path.exists(tmp_session + "-wal")
        assert os.path.exists(tmp_session + ".corrupt-backup")


# ── recovery must never reach the destructive force=True path ──────────────
def _source_without_comments(fn):
    out = []
    for line in inspect.getsource(fn).splitlines():
        # Drop full-line and trailing comments so a comment that merely
        # mentions a name isn't mistaken for a call.
        code = line.split("#", 1)[0]
        out.append(code)
    return "\n".join(out)


class TestRecoveryNeverForces:
    @pytest.mark.parametrize("method_name", [
        "restore_connections",
        "_auto_reconnect",
        "reconnect",
        "_socket_heartbeat",
        "_restore_session_from_db",
    ])
    def test_recovery_methods_do_not_call_start_pairing(self, method_name):
        code = _source_without_comments(getattr(wa_mod.WhatsAppService, method_name))
        assert "start_pairing" not in code, (
            f"{method_name} calls start_pairing — recovery must never trigger "
            "the destructive force re-pair (design §6)"
        )


# ── graceful drain behaviour (C1-1..C1-4, C1-6) ────────────────────────────
class TestDrain:
    async def test_draining_gate_refuses_new_chat_turn(self, service):
        service._draining = True
        # Returns None before touching the DB / agent pipeline.
        result = await service._process_through_agent("tenant-abc", "sender", "hi")
        assert result is None

    def test_handle_inbound_has_draining_gate(self):
        # The true inbound entrypoint rejects before the expensive media path.
        code = _source_without_comments(wa_mod.WhatsAppService._handle_inbound)
        assert "self._draining" in code

    async def test_drain_waits_for_inflight_then_completes(self, service):
        service._inflight_turns = 1

        async def _finish():
            await asyncio.sleep(0.2)
            service._inflight_turns = 0

        asyncio.ensure_future(_finish())
        await service.drain_and_shutdown(drain_deadline=5, disconnect_timeout=0.1)
        assert service._draining is True
        assert service._inflight_turns == 0

    async def test_drain_cancels_recovery_tasks(self, service):
        t = asyncio.ensure_future(asyncio.sleep(100))
        service._heartbeat_tasks["tenant-abc:default"] = t
        await service.drain_and_shutdown(drain_deadline=1, disconnect_timeout=0.1)
        # The maps are cleared up front (the contract); let the loop settle the
        # cancellation it requested, then confirm the task is torn down.
        await asyncio.sleep(0)
        assert service._heartbeat_tasks == {}
        assert t.cancelled() or t.done()

    async def test_auto_reconnect_short_circuits_when_draining(self, service):
        service._draining = True
        await service._auto_reconnect("tenant-abc", "default")
        # Returned before incrementing the attempt counter.
        assert service._reconnect_counts.get("tenant-abc:default") is None

    async def test_reconnect_short_circuits_when_draining(self, service):
        service._draining = True
        result = await service.reconnect("tenant-abc", "default")
        assert result == {"status": "draining"}
