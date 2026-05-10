"""Phase 1.5 cross-runtime smoke — the canonical ``cli_orchestrator``
package mounted at ``<repo-root>/packages/cli_orchestrator/`` must be
importable from inside the code-worker runtime exactly as it is from
inside the API runtime. These three tests catch any future regression
of the I-1 deviation (the worker COPY/bind-mount falling out of sync
with the Dockerfile or docker-compose context).

Why three small tests instead of one:
  - test 1 pins the import surface at the package level.
  - test 2 pins the classifier behavioural contract.
  - test 3 pins the redaction surface so the worker can't quietly drop
    SENSITIVE_ENV_KEYS coverage when Phase 2 starts using it.

These run inside the worker test harness (apps/code-worker/tests/) on
purpose — the conftest there adds <repo-root>/packages/ to sys.path,
mirroring the production COPY. If the wiring breaks, these tests fail.
"""
from __future__ import annotations


def test_canonical_package_importable_from_worker() -> None:
    """The top-level ``cli_orchestrator`` import must succeed from the
    worker test harness — same code path as production, where the
    Dockerfile COPYs packages/cli_orchestrator into /app/."""
    import cli_orchestrator  # noqa: F401  exercise the import itself

    # Assert the public surface the Phase 1 plan locked in.
    expected = {
        "Status",
        "classify",
        "classify_with_legacy_label",
        "redact",
        "redact_json_structural",
        "cleanup_codex_home",
        "SENSITIVE_ENV_KEYS",
    }
    actual = set(cli_orchestrator.__all__)
    assert expected <= actual, (
        f"cli_orchestrator.__all__ regressed; missing: {expected - actual}"
    )


def test_classifier_quota_exhausted_contract() -> None:
    """The classifier returns Status.QUOTA_EXHAUSTED for the canonical
    'rate limit' literal — same behavioural seam the worker helpers
    will delegate to in step 5."""
    from cli_orchestrator import Status, classify

    assert classify("rate limit reached") == Status.QUOTA_EXHAUSTED
    assert classify("credit balance is too low") == Status.QUOTA_EXHAUSTED


def test_redaction_sensitive_env_keys_present() -> None:
    """The SENSITIVE_ENV_KEYS export must reach the worker runtime so
    Phase 2 adapter sandboxing can rely on it."""
    from cli_orchestrator import SENSITIVE_ENV_KEYS

    # Type contract: a non-empty set of strings.
    assert isinstance(SENSITIVE_ENV_KEYS, (set, frozenset))
    assert len(SENSITIVE_ENV_KEYS) > 0
    assert all(isinstance(k, str) for k in SENSITIVE_ENV_KEYS)
