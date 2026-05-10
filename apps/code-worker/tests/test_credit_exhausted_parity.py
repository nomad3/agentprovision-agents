"""Phase 1.5 corpus-parity test — every literal in the legacy
``CLAUDE_CREDIT_ERROR_PATTERNS`` / ``CODEX_CREDIT_ERROR_PATTERNS`` /
``COPILOT_CREDIT_ERROR_PATTERNS`` tuples in ``apps/code-worker/workflows.py``
must classify to the chain-fallback-triggering status set via the
canonical ``cli_orchestrator.classify``. This pins behavioural
equivalence between the two paths so step 5 (helper rewrite to
delegate to ``classify``) is provably non-behavioural for the corpus.

The chain-fallback-triggering status set is per-platform:

* claude / codex → ``{QUOTA_EXHAUSTED}``
* copilot → ``{QUOTA_EXHAUSTED, NEEDS_AUTH}`` — the legacy COPILOT
  helper lumped "not authorized" into the credit-exhausted bucket
  to trigger CLI fallback on auth failures. Phase 1.5 keeps auth
  a distinct ``Status`` for other consumers (chat footer, RL,
  council) and the copilot helper takes the union explicitly.

Two test classes:

* ``TestLegacyCorpusClassifiesToFallbackTrigger`` — the parametrised
  parity check.

* ``TestHelpersDelegateToClassifier`` — once step 5 lands, the three
  helpers ``_is_*_credit_exhausted`` MUST agree with the per-platform
  fallback status set on every legacy fragment.

The legacy tuples are kept ONE phase as dead-code corpus per the plan;
Phase 2 deletes them.
"""
from __future__ import annotations

import pytest

import workflows as wf
from cli_orchestrator import Status, classify

# Per-platform fallback-triggering status set. Step 5 helpers use these
# exact sets when delegating to ``classify``.
_FALLBACK_STATUSES: dict[str, frozenset[Status]] = {
    "claude": frozenset({Status.QUOTA_EXHAUSTED}),
    "codex": frozenset({Status.QUOTA_EXHAUSTED}),
    "copilot": frozenset({Status.QUOTA_EXHAUSTED, Status.NEEDS_AUTH}),
}


# All credit-exhaustion fragments from workflows.py. Pulled live from
# the module so a future tuple edit (or removal) is reflected without
# duplicating the literals here.
_ALL_LEGACY_PATTERNS: list[tuple[str, str]] = [
    *(("claude", p) for p in wf.CLAUDE_CREDIT_ERROR_PATTERNS),
    *(("codex", p) for p in wf.CODEX_CREDIT_ERROR_PATTERNS),
    *(("copilot", p) for p in wf.COPILOT_CREDIT_ERROR_PATTERNS),
]


# ── Class 1 — every legacy fragment hits the fallback status set ──────

class TestLegacyCorpusClassifiesToFallbackTrigger:
    """Every literal in the three legacy pattern tuples, when handed
    to ``cli_orchestrator.classify``, MUST land in the per-platform
    fallback-triggering status set. If this fails for a given fragment
    the classifier's stderr rules have a coverage gap that step 5's
    helper rewrite would silently introduce as a behavioural drift."""

    @pytest.mark.parametrize(
        "platform,pattern",
        _ALL_LEGACY_PATTERNS,
        ids=[f"{plat}::{p}" for plat, p in _ALL_LEGACY_PATTERNS],
    )
    def test_pattern_classifies_to_fallback_trigger(
        self, platform: str, pattern: str
    ) -> None:
        # The legacy helpers do `pattern in error_text.lower()`, so the
        # fragment is matched as a substring of lowercase stderr. Feed
        # the bare pattern (already lowercase in the tuples) — that's
        # the minimal stderr the legacy helper would have accepted.
        result = classify(pattern)
        expected = _FALLBACK_STATUSES[platform]
        assert result in expected, (
            f"{platform} legacy fragment {pattern!r} classified to "
            f"{result!r}, not in expected fallback set {expected}; "
            f"step 5 helper rewrite would change CLI-chain behaviour"
        )


# ── Class 2 — once step 5 lands, helpers MUST agree with classify ──────

class TestHelpersDelegateToClassifier:
    """The three ``_is_*_credit_exhausted`` helpers in workflows.py and
    ``cli_orchestrator.classify`` must agree on every legacy fragment.

    Pre-step-5: legacy helpers walk the tuples directly and always
    return True for these fragments → this class passes iff the
    classifier also lands in the per-platform fallback set (same
    coverage gate as Class 1).

    Post-step-5: the helpers ARE
    ``classify(...) in _FALLBACK_STATUSES[platform]`` so this class
    becomes tautologically true on the corpus. The point is to keep
    the parity assertion in tree past Phase 2, when the legacy tuples
    are deleted, by reusing the corpus."""

    def _classify_via_helper(self, platform: str, text: str) -> bool:
        if platform == "claude":
            return wf._is_claude_credit_exhausted(text)
        if platform == "codex":
            return wf._is_codex_credit_exhausted(text)
        if platform == "copilot":
            return wf._is_copilot_credit_exhausted(text)
        raise ValueError(platform)

    @pytest.mark.parametrize(
        "platform,pattern",
        _ALL_LEGACY_PATTERNS,
        ids=[f"{plat}::{p}" for plat, p in _ALL_LEGACY_PATTERNS],
    )
    def test_helper_and_classifier_agree(
        self, platform: str, pattern: str
    ) -> None:
        helper_says_exhausted = self._classify_via_helper(platform, pattern)
        classifier_says_exhausted = (
            classify(pattern) in _FALLBACK_STATUSES[platform]
        )
        assert helper_says_exhausted == classifier_says_exhausted, (
            f"{platform} parity drift on {pattern!r}: helper="
            f"{helper_says_exhausted}, classifier-in-fallback-set="
            f"{classifier_says_exhausted}"
        )

    def test_none_input_both_paths_say_false(self) -> None:
        """Defensive: helpers accept None; classifier accepts ''."""
        for platform in ("claude", "codex", "copilot"):
            assert (
                self._classify_via_helper(platform, None)  # type: ignore[arg-type]
                is False
            )
        # classify("") falls through to UNKNOWN_FAILURE, which is not
        # in any fallback set.
        for fallback in _FALLBACK_STATUSES.values():
            assert classify("") not in fallback
