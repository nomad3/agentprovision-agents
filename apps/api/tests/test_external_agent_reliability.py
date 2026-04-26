"""Unit tests for the external_agent_call reliability shim."""
import os
os.environ["TESTING"] = "True"

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import external_agent_reliability as rel


def _agent(**overrides):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="ext-agent",
        protocol="webhook",
        endpoint_url="https://example.test/tasks",
        auth_type="bearer",
        credential_id=None,
        status="online",
        metadata_={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _DB:
    """Stand-in: db.add/commit no-op; db.query returns canned rows."""
    def __init__(self, rows=None):
        self._rows = rows or []
        self.commits = 0
    def add(self, _row): pass
    def commit(self): self.commits += 1
    def query(self, _model):
        rows = self._rows
        class Q:
            def filter(self, *a, **k): return self
            def first(self_inner):
                return rows[0] if rows else None
        return Q()


@pytest.fixture(autouse=True)
def _stub_redis(monkeypatch):
    """Default: Redis disabled so breaker is no-op. Tests that need
    breaker behavior install a fake explicitly.
    """
    monkeypatch.setattr(rel, "_get_redis", lambda: None)
    yield


# ---------------------------------------------------------------------------
# Happy path / retry
# ---------------------------------------------------------------------------

def test_call_returns_dispatch_result_on_first_attempt():
    agent = _agent()
    db = _DB()
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.return_value = "ok"
        out = rel.external_agent_call(agent, "task", {}, db)
    assert out == "ok"
    assert agent.status == "online"


def test_call_retries_then_succeeds(monkeypatch):
    """Simulate two failures then a success — must eventually return."""
    agent = _agent()
    db = _DB()
    monkeypatch.setattr(rel.time, "sleep", lambda *_a: None)
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.side_effect = [RuntimeError("boom"), RuntimeError("boom"), "third-try-ok"]
        out = rel.external_agent_call(agent, "task", {}, db)
    assert out == "third-try-ok"
    assert a.dispatch.call_count == 3


def test_call_exhausts_retries_and_marks_error(monkeypatch):
    agent = _agent()
    db = _DB()
    monkeypatch.setattr(rel.time, "sleep", lambda *_a: None)
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.side_effect = RuntimeError("nope")
        with pytest.raises(RuntimeError, match="nope"):
            rel.external_agent_call(agent, "task", {}, db)
    assert agent.status == "error"
    assert a.dispatch.call_count == rel.MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def test_fallback_dispatched_after_exhausting_retries(monkeypatch):
    primary = _agent(metadata_={"fallback_agent_id": str(uuid.uuid4())})
    fallback = _agent(name="fallback-agent")
    monkeypatch.setattr(rel.time, "sleep", lambda *_a: None)
    db = _DB(rows=[fallback])
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.side_effect = [
            RuntimeError("primary fail"),
            RuntimeError("primary fail"),
            RuntimeError("primary fail"),
            "fallback-ok",
        ]
        out = rel.external_agent_call(primary, "task", {}, db)
    assert out == "fallback-ok"


def test_fallback_recursion_capped_at_depth_one(monkeypatch):
    primary = _agent(metadata_={"fallback_agent_id": str(uuid.uuid4())})
    fallback = _agent(name="fallback-agent", metadata_={"fallback_agent_id": str(uuid.uuid4())})
    monkeypatch.setattr(rel.time, "sleep", lambda *_a: None)
    db = _DB(rows=[fallback])
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.side_effect = RuntimeError("nope")
        # Both primary + fallback fail — should NOT recurse beyond depth 1.
        with pytest.raises(RuntimeError):
            rel.external_agent_call(primary, "task", {}, db)
    # 2 agents × 3 attempts = 6 dispatch calls, no further recursion.
    assert a.dispatch.call_count == rel.MAX_ATTEMPTS * 2


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self, breaker_open=False):
        self.store: dict = {}
        if breaker_open:
            self.store[rel._BREAKER_KEY_FMT.format(external_agent_id="x")] = "1"
    def exists(self, key):
        return 1 if key in self.store else 0
    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]
    def expire(self, *_a, **_k): pass
    def set(self, key, value, ex=None):
        self.store[key] = value
    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


def test_breaker_opens_after_threshold_failures(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rel, "_get_redis", lambda: fake)
    monkeypatch.setattr(rel.time, "sleep", lambda *_a: None)
    agent = _agent(id="aaaaaaaa-0000-0000-0000-000000000000")
    # Adjust threshold to 2 so we can test in fewer iterations.
    monkeypatch.setattr(rel, "BREAKER_THRESHOLD", 2)
    db = _DB()
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.side_effect = RuntimeError("nope")
        # First call: 3 retries, increments fail counter once → breaker not yet open.
        with pytest.raises(RuntimeError):
            rel.external_agent_call(agent, "t", {}, db)
        # Second call: another increment → trips breaker after second hard failure.
        with pytest.raises(RuntimeError):
            rel.external_agent_call(agent, "t", {}, db)
    breaker_key = rel._BREAKER_KEY_FMT.format(external_agent_id=str(agent.id))
    assert breaker_key in fake.store


def test_open_breaker_short_circuits_to_fallback(monkeypatch):
    fake = _FakeRedis()
    primary = _agent(id="bbbbbbbb-0000-0000-0000-000000000000",
                     metadata_={"fallback_agent_id": str(uuid.uuid4())})
    fallback = _agent(name="fb")
    fake.store[rel._BREAKER_KEY_FMT.format(external_agent_id=str(primary.id))] = "1"
    monkeypatch.setattr(rel, "_get_redis", lambda: fake)
    db = _DB(rows=[fallback])
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.return_value = "fb-ok"
        out = rel.external_agent_call(primary, "t", {}, db)
    assert out == "fb-ok"
    assert primary.status == "breaker_open"


def test_success_clears_breaker_state(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rel, "_get_redis", lambda: fake)
    agent = _agent(id="cccccccc-0000-0000-0000-000000000000")
    # Pre-load some failure count for the agent.
    fake.store[rel._FAIL_COUNT_KEY_FMT.format(external_agent_id=str(agent.id))] = 3
    db = _DB()
    with patch("app.services.external_agent_adapter.adapter") as a:
        a.dispatch.return_value = "ok"
        rel.external_agent_call(agent, "t", {}, db)
    # Counter cleared on success.
    assert rel._FAIL_COUNT_KEY_FMT.format(external_agent_id=str(agent.id)) not in fake.store
