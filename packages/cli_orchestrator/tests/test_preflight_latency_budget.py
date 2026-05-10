"""Latency budget tests for the 5 preflight helpers — Phase 3 commit 1.

Plan §2.3 budgets (warm state, p95):

  - check_binary_on_path:           < 1ms
  - check_workspace_trust_file:     < 1ms
  - check_credentials_present:      < 5ms
  - check_cloud_api_enabled:        < 1ms cached
  - check_temporal_queue_reachable: < 1ms cached

Each helper is run 1000x with stub callables and we assert the p95
falls inside the budget. The real-world helpers add network I/O,
which is what the cache-hit path is for; the tests here exercise
the warm-state path (cache populated or memoised).

Note on numbers: budgets are realistic for warm state, not the
worst-case uncached probe. The Phase 3 ship gate is the warm-state
p95 — that's what the dashboard alerts on.
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


def _p95(durations: list[float]) -> float:
    if not durations:
        return 0.0
    s = sorted(durations)
    idx = int(len(s) * 0.95)
    return s[min(idx, len(s) - 1)]


def _measure(fn, n=1000) -> list[float]:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_caches()
    yield
    clear_caches()


def test_binary_on_path_p95_under_1ms(monkeypatch):
    """Cold call seeds memo; subsequent 999 calls are dict lookups."""
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/x",
    )
    durations = _measure(lambda: check_binary_on_path("x"))
    p95 = _p95(durations)
    assert p95 < 1.0, f"binary_on_path p95={p95:.3f}ms exceeds 1ms budget"


def test_workspace_trust_file_p95_under_1ms(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("ok")
    durations = _measure(lambda: check_workspace_trust_file(str(p)))
    p95 = _p95(durations)
    assert p95 < 1.0, f"workspace_trust_file p95={p95:.3f}ms exceeds 1ms budget"


def test_credentials_present_p95_under_5ms():
    fetch = lambda integration, tenant: {"oauth_token": "x"}
    durations = _measure(
        lambda: check_credentials_present(
            fetch=fetch, tenant_id="t", platform="claude_code",
        ),
    )
    p95 = _p95(durations)
    assert p95 < 5.0, f"credentials_present p95={p95:.3f}ms exceeds 5ms budget"


def test_cloud_api_enabled_p95_cached_under_1ms():
    cache = {"cli_orchestrator:preflight:cloud_api:t:gemini_cli": b"1"}

    def get(k):
        return cache.get(k)

    def boom():
        raise AssertionError("probe should not run on cache hit")

    durations = _measure(
        lambda: check_cloud_api_enabled(
            redis_get=get,
            redis_setex=lambda k, ttl, v: None,
            probe=boom,
            tenant_id="t", platform="gemini_cli",
        ),
    )
    p95 = _p95(durations)
    assert p95 < 1.0, f"cloud_api_enabled (cached) p95={p95:.3f}ms exceeds 1ms budget"


def test_temporal_queue_reachable_p95_cached_under_1ms():
    cache = {"cli_orchestrator:preflight:temporal_queue:agentprovision-code": b"1"}

    def boom():
        raise AssertionError("probe should not run on cache hit")

    durations = _measure(
        lambda: check_temporal_queue_reachable(
            redis_get=lambda k: cache.get(k),
            redis_setex=lambda k, ttl, v: None,
            heartbeat_probe=boom,
        ),
    )
    p95 = _p95(durations)
    assert p95 < 1.0, f"temporal_queue_reachable (cached) p95={p95:.3f}ms exceeds 1ms budget"
