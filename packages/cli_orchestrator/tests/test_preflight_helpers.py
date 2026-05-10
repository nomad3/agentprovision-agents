"""Unit tests for the 5 preflight shared helpers — Phase 3 commit 1.

Each helper gets:
  - happy path
  - miss / failure path
  - cache-hit path (where the helper memoises)

The helpers use callable injection so tests can inject simple
in-memory stubs — no Redis, no Temporal client, no FastEmbed.
"""
from __future__ import annotations

import time

import pytest

from cli_orchestrator.preflight import (
    check_binary_on_path,
    check_cloud_api_enabled,
    check_credentials_present,
    check_temporal_queue_reachable,
    check_workspace_trust_file,
    clear_caches,
)
from cli_orchestrator.status import Status


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_caches()
    yield
    clear_caches()


# ── check_binary_on_path ─────────────────────────────────────────────────

def test_binary_on_path_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which",
        lambda name: "/usr/local/bin/" + name,
    )
    result = check_binary_on_path("claude")
    assert result.ok is True
    assert result.status is None


def test_binary_on_path_miss(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    result = check_binary_on_path("nonsuch")
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE
    assert "nonsuch" in result.reason


def test_binary_on_path_cache_hit(monkeypatch):
    """Second call must NOT re-run shutil.which."""
    calls = {"n": 0}

    def fake_which(name):
        calls["n"] += 1
        return "/bin/x"

    monkeypatch.setattr("cli_orchestrator.preflight.shutil.which", fake_which)
    check_binary_on_path("x")
    check_binary_on_path("x")
    assert calls["n"] == 1


# ── check_workspace_trust_file ───────────────────────────────────────────

def test_workspace_trust_file_happy(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[trust]\nlevel = 1\n")
    result = check_workspace_trust_file(str(p))
    assert result.ok is True


def test_workspace_trust_file_miss(tmp_path):
    p = tmp_path / "missing.toml"
    result = check_workspace_trust_file(str(p))
    assert result.ok is False
    assert result.status is Status.WORKSPACE_UNTRUSTED


def test_workspace_trust_file_cache_hit(tmp_path, monkeypatch):
    """Second call must NOT re-run Path.exists()."""
    p = tmp_path / "config.toml"
    p.write_text("ok")
    calls = {"n": 0}
    real_exists = type(p).exists

    def fake_exists(self):
        calls["n"] += 1
        return real_exists(self)

    monkeypatch.setattr("cli_orchestrator.preflight.Path.exists", fake_exists)
    check_workspace_trust_file(str(p))
    check_workspace_trust_file(str(p))
    assert calls["n"] == 1


# ── check_credentials_present ────────────────────────────────────────────

def test_credentials_present_happy():
    fetch = lambda integration, tenant: {"oauth_token": "x"}
    result = check_credentials_present(fetch=fetch, tenant_id="t", platform="claude_code")
    assert result.ok is True


def test_credentials_present_miss():
    fetch = lambda integration, tenant: None
    result = check_credentials_present(fetch=fetch, tenant_id="t", platform="claude_code")
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_credentials_present_fetch_raises():
    def fetch(integration, tenant):
        raise RuntimeError("vault down")
    result = check_credentials_present(fetch=fetch, tenant_id="t", platform="codex")
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_credentials_present_empty_dict():
    fetch = lambda integration, tenant: {}
    result = check_credentials_present(fetch=fetch, tenant_id="t", platform="codex")
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


# ── check_cloud_api_enabled ──────────────────────────────────────────────

def test_cloud_api_enabled_happy_uncached():
    cache = {}

    def get(k):
        return cache.get(k)

    def setex(k, ttl, v):
        cache[k] = v.encode() if isinstance(v, str) else v

    result = check_cloud_api_enabled(
        redis_get=get, redis_setex=setex,
        probe=lambda: True, tenant_id="t", platform="gemini_cli",
    )
    assert result.ok is True
    # Cache stamped "1"
    assert b"1" in cache.get("cli_orchestrator:preflight:cloud_api:t:gemini_cli", b"")


def test_cloud_api_enabled_disabled_uncached():
    cache = {}
    result = check_cloud_api_enabled(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: cache.update({k: v.encode()}),
        probe=lambda: False, tenant_id="t", platform="gemini_cli",
    )
    assert result.ok is False
    assert result.status is Status.API_DISABLED


def test_cloud_api_enabled_cache_hit_skips_probe():
    cache = {"cli_orchestrator:preflight:cloud_api:t:gemini_cli": b"1"}

    def boom_probe():
        raise AssertionError("probe should not run on cache hit")

    result = check_cloud_api_enabled(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: None,
        probe=boom_probe, tenant_id="t", platform="gemini_cli",
    )
    assert result.ok is True


def test_cloud_api_enabled_cache_zero_returns_disabled():
    cache = {"cli_orchestrator:preflight:cloud_api:t:gemini_cli": b"0"}
    result = check_cloud_api_enabled(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: None,
        probe=lambda: True,  # would say enabled but cache says no
        tenant_id="t", platform="gemini_cli",
    )
    assert result.ok is False
    assert result.status is Status.API_DISABLED


def test_cloud_api_enabled_redis_unavailable_falls_through_to_probe():
    def boom_get(k):
        raise ConnectionError("redis down")

    def silent_setex(k, ttl, v):
        raise ConnectionError("redis down")

    result = check_cloud_api_enabled(
        redis_get=boom_get, redis_setex=silent_setex,
        probe=lambda: True, tenant_id="t", platform="copilot_cli",
    )
    assert result.ok is True


def test_cloud_api_enabled_probe_raises_caches_disabled():
    cache = {}

    def setex(k, ttl, v):
        cache[k] = v.encode() if isinstance(v, str) else v

    result = check_cloud_api_enabled(
        redis_get=lambda k: cache.get(k), redis_setex=setex,
        probe=lambda: (_ for _ in ()).throw(RuntimeError("HTTP 500")),
        tenant_id="t", platform="copilot_cli",
    )
    assert result.ok is False
    assert result.status is Status.API_DISABLED


# ── check_temporal_queue_reachable ──────────────────────────────────────

def test_temporal_queue_reachable_happy_fresh_heartbeat():
    cache = {}
    now = time.time()
    result = check_temporal_queue_reachable(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: cache.update({k: v.encode()}),
        heartbeat_probe=lambda: now - 5.0,  # 5s ago — fresh
    )
    assert result.ok is True


def test_temporal_queue_reachable_stale_heartbeat():
    now = time.time()
    result = check_temporal_queue_reachable(
        redis_get=lambda k: None, redis_setex=lambda k, ttl, v: None,
        heartbeat_probe=lambda: now - 600.0,  # 10min ago — stale
    )
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_temporal_queue_reachable_no_heartbeat_at_all():
    result = check_temporal_queue_reachable(
        redis_get=lambda k: None, redis_setex=lambda k, ttl, v: None,
        heartbeat_probe=lambda: None,
    )
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_temporal_queue_reachable_cache_hit_skips_probe():
    cache = {"cli_orchestrator:preflight:temporal_queue:agentprovision-code": b"1"}

    def boom():
        raise AssertionError("probe should not run on cache hit")

    result = check_temporal_queue_reachable(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: None,
        heartbeat_probe=boom,
    )
    assert result.ok is True


def test_temporal_queue_reachable_cache_zero_returns_unavailable():
    cache = {"cli_orchestrator:preflight:temporal_queue:agentprovision-code": b"0"}
    result = check_temporal_queue_reachable(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: None,
        heartbeat_probe=lambda: time.time(),  # would say fresh but cache says no
    )
    assert result.ok is False


def test_temporal_queue_reachable_probe_raises():
    cache = {}

    def boom():
        raise ConnectionError("redis down")

    result = check_temporal_queue_reachable(
        redis_get=lambda k: cache.get(k),
        redis_setex=lambda k, ttl, v: cache.update({k: v.encode()}),
        heartbeat_probe=boom,
    )
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE
