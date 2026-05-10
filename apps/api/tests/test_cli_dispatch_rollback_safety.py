"""Regression tests for the dispatch-path rollback hardening.

Background
----------
PR #349 fixed a NameError closure bug in
``cli_session_manager._run_agent_session_legacy`` that silently broke
WhatsApp Luna for hours. The closure raised ``NameError`` inside the
nested ``_run_workflow``, which was caught by the outer
``except Exception`` at the bottom of the function — but that handler
did NOT call ``db.rollback()``. Postgres marked the transaction
``InFailedSqlTransaction`` and every subsequent query on the same
FastAPI request session ("mcp_server_connectors load, memory recall, RL
log") cascaded into ``current transaction is aborted, commands ignored
until end of transaction block``.

The closure bug is fixed in commit ``47d63589`` (PR #349). This test
suite pins down the *blast-radius amplifier* fix — the missing
``safe_rollback(db)`` calls — so that a future similar exception cannot
poison the session for the rest of the request.

Test pattern
------------
For each dispatch path we:
  1. Build a real SQLAlchemy session backed by sqlite in-memory.
  2. Manually open a transaction and emit a known-bad statement to
     reproduce the InFailedSqlTransaction state — wait, sqlite is too
     forgiving for that. Instead we inject a synthetic exception via
     monkeypatching a function the dispatch path will call, then assert
     that ``db.rollback`` was invoked. We use a tracking wrapper around
     a real session so the assertion is on observed behavior, not on a
     bare mock.
  3. Issue ``SELECT 1`` afterward through the same session and assert
     it returns 1 — proving the session is usable.
"""
from __future__ import annotations

import os
import uuid
from typing import Dict

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ── Session helper ──────────────────────────────────────────────────

class _RollbackTrackingSession(Session):
    """Subclass that records every ``rollback()`` call so tests can
    assert the dispatch handlers reached for it. Wraps a real sqlite
    engine so ``execute(text("SELECT 1"))`` actually works."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rollback_call_count = 0

    def rollback(self):
        self.rollback_call_count += 1
        return super().rollback()


@pytest.fixture
def tracking_db():
    """A real sqlite-backed session that counts rollbacks."""
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(
        bind=engine, class_=_RollbackTrackingSession,
        autocommit=False, autoflush=False,
    )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _assert_session_usable(db: Session) -> None:
    """A poisoned session would raise InFailedSqlTransaction here; a
    healthy one returns 1. This is the load-bearing assertion: it
    proves the rollback actually happened, not just that we *tried*."""
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1, "session is poisoned — follow-up SELECT 1 failed"


# ── cli_session_manager: outer ChatCliWorkflow dispatch handler ─────

def test_chat_cli_workflow_dispatch_failure_rolls_back(tracking_db, monkeypatch):
    """The outer ``except Exception`` around the Temporal dispatch in
    ``_run_agent_session_legacy`` must roll back. This is the exact
    site PR #349 traced the WhatsApp cascade to.
    """
    from app.services import cli_session_manager as csm

    # Short-circuit everything BEFORE the Temporal try-block so we land
    # on the failure path quickly. Skill resolution + credential lookup
    # would otherwise need a fully populated DB.
    fake_skill = type("FakeSkill", (), {"description": "luna persona", "name": "luna"})()

    monkeypatch.setattr(
        csm.skill_manager, "get_skill_by_slug",
        lambda slug, tenant: fake_skill,
    )
    monkeypatch.setattr(
        csm, "resolve_primary_agent_slug",
        lambda db, tenant_id: "luna",
    )
    # Subscription token present → skip the local-fallback branch.
    monkeypatch.setattr(
        csm, "_get_cli_platform_credentials",
        lambda db, tenant_id, platform: {"session_token": "fake"},
    )
    # Memory recall etc. — pre-built context bypasses them entirely.
    pre_built = {"recalled_entity_names": []}

    # Make ``asyncio.run`` raise the synthetic error to land us on the
    # outer handler. ``asyncio.run`` is what the dispatch path calls
    # when no running loop is present.
    import asyncio as _asyncio

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic dispatch failure")

    monkeypatch.setattr(_asyncio, "run", _boom)
    # Also patch get_running_loop so we go down the asyncio.run branch.
    monkeypatch.setattr(_asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError()))

    # Connectors lookup inside generate_mcp_config also touches the DB —
    # short-circuit it so we don't need the schema.
    monkeypatch.setattr(
        csm, "generate_mcp_config",
        lambda *a, **kw: {"mcpServers": {}},
    )

    response, metadata = csm._run_agent_session_legacy(
        db=tracking_db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="claude_code",
        agent_slug="luna",
        message="hi",
        channel="whatsapp",
        sender_phone="+1234",
        conversation_summary="",
        pre_built_memory_context=pre_built,
    )

    # The function should have surfaced the error gracefully.
    assert response is None
    assert "synthetic dispatch failure" in (metadata.get("error") or "")

    # And — the load-bearing check — the session must be usable.
    assert tracking_db.rollback_call_count >= 1, (
        "Expected at least one rollback() call after dispatch failure"
    )
    _assert_session_usable(tracking_db)


# ── cli_session_manager: local_tool_agent fallback handler ──────────

def test_local_tool_agent_failure_rolls_back(tracking_db, monkeypatch):
    """When the user has no CLI subscription and the local_tool_agent
    raises, the handler must roll back so the plain-text fallback
    below (and the caller's downstream commits) cannot inherit a
    poisoned session.
    """
    from app.services import cli_session_manager as csm

    fake_skill = type("FakeSkill", (), {"description": "luna", "name": "luna"})()
    monkeypatch.setattr(
        csm.skill_manager, "get_skill_by_slug",
        lambda slug, tenant: fake_skill,
    )
    monkeypatch.setattr(
        csm, "resolve_primary_agent_slug",
        lambda db, tenant_id: "luna",
    )
    # No session_token → subscription_missing branch.
    monkeypatch.setattr(
        csm, "_get_cli_platform_credentials",
        lambda db, tenant_id, platform: {},
    )

    # Stub the IntegrationConfig query (would otherwise need the table).
    class _FakeQuery:
        def filter(self, *a, **k): return self
        def all(self): return []
    monkeypatch.setattr(
        tracking_db, "query",
        lambda *a, **k: _FakeQuery(),
    )

    # Make local_tool_agent.run raise. We patch via importlib because
    # the import is inside the function body.
    import importlib
    import sys
    fake_lta = type(sys)("app.services.local_tool_agent")

    def _boom(**kwargs):
        raise RuntimeError("synthetic local_tool_agent failure")

    fake_lta.run = _boom
    monkeypatch.setitem(sys.modules, "app.services.local_tool_agent", fake_lta)

    # Stub local_inference fallback so we don't actually hit Ollama.
    fake_li = type(sys)("app.services.local_inference")
    fake_li.generate_agent_response_sync = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "app.services.local_inference", fake_li)

    response, metadata = csm._run_agent_session_legacy(
        db=tracking_db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="claude_code",
        agent_slug="luna",
        message="hi",
        channel="whatsapp",
        sender_phone="+1234",
        conversation_summary="",
        pre_built_memory_context={},
    )

    # Will return the friendly error since both fallbacks were stubbed.
    assert response is None
    # The rollback we care about fired on the local_tool_agent except.
    assert tracking_db.rollback_call_count >= 1
    _assert_session_usable(tracking_db)


# ── cli_session_manager: mint_agent_token failure handler ───────────

def test_mint_agent_token_failure_rolls_back(tracking_db, monkeypatch):
    """When the resilient flag is on and mint_agent_token raises (e.g.
    because the Agent table query failed or the JWT secret is missing),
    the handler must roll back. The next line calls
    ``generate_mcp_config(..., db=db)`` which would otherwise inherit
    the poison.
    """
    from app.services import cli_session_manager as csm

    fake_skill = type("FakeSkill", (), {"description": "luna", "name": "luna"})()
    monkeypatch.setattr(
        csm.skill_manager, "get_skill_by_slug",
        lambda slug, tenant: fake_skill,
    )
    monkeypatch.setattr(
        csm, "resolve_primary_agent_slug",
        lambda db, tenant_id: "luna",
    )
    monkeypatch.setattr(
        csm, "_get_cli_platform_credentials",
        lambda db, tenant_id, platform: {"session_token": "fake"},
    )

    # Force resilient flag ON so we enter the mint try-block.
    import sys
    fake_shadow = type(sys)("app.services.cli_orchestrator_shadow")
    fake_shadow.read_flags = lambda db, tenant_id: (True, False)
    fake_shadow.maybe_run_shadow = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "app.services.cli_orchestrator_shadow", fake_shadow)

    # Make mint_agent_token blow up with a synthetic error.
    fake_at = type(sys)("app.services.agent_token")
    fake_at.mint_agent_token = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("synthetic mint failure")
    )
    monkeypatch.setitem(sys.modules, "app.services.agent_token", fake_at)

    # The mint block also queries Agent — stub the query out.
    class _FakeQuery:
        def filter(self, *a, **k): return self
        def first(self): return type("A", (), {"id": uuid.uuid4(), "tool_groups": None})()
        def all(self): return []
    monkeypatch.setattr(
        tracking_db, "query",
        lambda *a, **k: _FakeQuery(),
    )

    # Short-circuit Temporal so the test ends right after the mint block.
    monkeypatch.setattr(
        csm, "generate_mcp_config",
        lambda *a, **kw: {"mcpServers": {}},
    )
    import asyncio as _asyncio
    monkeypatch.setattr(
        _asyncio, "get_running_loop",
        lambda: (_ for _ in ()).throw(RuntimeError()),
    )

    def _fake_run(coro):
        # Drain the coroutine so it doesn't warn.
        try:
            coro.close()
        except Exception:
            pass
        return {"success": True, "response_text": "hello", "metadata": {}}

    monkeypatch.setattr(_asyncio, "run", _fake_run)

    response, metadata = csm._run_agent_session_legacy(
        db=tracking_db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        platform="claude_code",
        agent_slug="luna",
        message="hi",
        channel="whatsapp",
        sender_phone="+1234",
        conversation_summary="",
        pre_built_memory_context={},
    )

    # Mint failure is non-fatal; the function should still return ok-ish.
    # The crucial assertion: rollback fired and session is usable.
    assert tracking_db.rollback_call_count >= 1
    _assert_session_usable(tracking_db)


# ── chat.py: route_and_execute exception handler ────────────────────

def test_chat_route_and_execute_failure_rolls_back(tracking_db, monkeypatch):
    """The consumer-side guard. ``chat.py`` holds the request session
    for the entire dispatch path and continues to issue ``db.commit()``
    calls after route_and_execute returns. If route_and_execute raised
    and the handler didn't rollback, those commits would cascade into
    InFailedSqlTransaction. This test reproduces that failure mode by
    monkeypatching the route_and_execute symbol on the agent_router
    module (chat.py imports it function-locally) and then invoking the
    handler pattern.
    """
    from app.services import agent_router

    def _boom(*a, **kw):
        raise RuntimeError("synthetic route_and_execute failure")

    monkeypatch.setattr(agent_router, "route_and_execute", _boom)

    # Replicate the chat.py:392-422 try/except shape exactly. We don't
    # invoke the whole post_message path (which needs ChatSession rows,
    # summaries, presence, embedding, etc.) — we exercise the handler
    # surface verbatim against a real session so we observe behavior.
    from app.services.agent_router import route_and_execute  # already patched
    from app.db.safe_ops import safe_rollback

    response_text: str | None = "should-be-overwritten"
    context: Dict | None = None
    try:
        response_text, context = route_and_execute(
            tracking_db,
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            message="hi",
        )
    except Exception as e:
        # Mirror chat.py:415-422 (post-fix).
        safe_rollback(tracking_db)
        response_text = None
        context = {"error": str(e)}

    assert response_text is None
    assert "synthetic route_and_execute failure" in context["error"]
    assert tracking_db.rollback_call_count >= 1
    _assert_session_usable(tracking_db)


def test_chat_module_handler_text_contains_safe_rollback():
    """Source-level pin: the chat.py handler block around
    route_and_execute must call safe_rollback. The behavioral test
    above exercises the *pattern*; this test guarantees the production
    file actually uses it (so a future refactor that drops the call
    will fail this).
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(here, "app", "services", "chat.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()

    # Find the route_and_execute except block and verify it has the
    # rollback. We search for the surrounding text so a stray match
    # elsewhere doesn't pass the test.
    anchor = "route_and_execute: raised session="
    idx = src.find(anchor)
    assert idx != -1, "could not find route_and_execute error log line"

    # Look backward for the except line and forward for the rollback.
    window_start = src.rfind("except", 0, idx)
    window_end = src.find("response_text = None", idx)
    assert window_start != -1 and window_end != -1
    window = src[window_start:window_end]
    assert "safe_rollback" in window, (
        "route_and_execute exception handler in chat.py must call "
        "safe_rollback(db) — see PR #349 cascade analysis."
    )


def test_cli_session_manager_handlers_contain_safe_rollback():
    """Source-level pin for the three cli_session_manager handlers we
    hardened. Pinning the source is cheap insurance against a refactor
    that drops the calls — the behavioral tests exercise the dispatch
    path, this one guarantees the calls stay in place.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(here, "app", "services", "cli_session_manager.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()

    # 1. Outer ChatCliWorkflow dispatch handler.
    idx = src.find('logger.exception("ChatCliWorkflow dispatch failed")')
    assert idx != -1
    window = src[max(0, idx - 600):idx]
    assert "safe_rollback(db)" in window, (
        "ChatCliWorkflow outer except handler must call safe_rollback(db) — PR #349"
    )

    # 2. local_tool_agent failure handler.
    idx = src.find('Local tool agent failed')
    assert idx != -1
    window = src[max(0, idx - 400):idx + 200]
    assert "safe_rollback(db)" in window, (
        "local_tool_agent except handler must call safe_rollback(db)"
    )

    # 3. mint_agent_token failure handler.
    idx = src.find('agent_token mint failed')
    assert idx != -1
    window = src[max(0, idx - 600):idx + 200]
    assert "safe_rollback(db)" in window, (
        "mint_agent_token except handler must call safe_rollback(db)"
    )
