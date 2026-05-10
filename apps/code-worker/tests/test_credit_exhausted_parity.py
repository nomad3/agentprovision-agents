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


# Phase 1.5 Important review I-A — INTENTIONAL NARROWING:
# the legacy CODEX_CREDIT_ERROR_PATTERNS tuple contained bare-token
# substrings ``billing`` and ``capacity`` that were too loose for the
# apps/api chat hot path (the classifier feeds both apps/code-worker
# AND cli_platform_resolver via the shim, and bare "capacity planning"
# in user prose would have falsely triggered cooldown + chain-skip on
# the active CLI). The classifier rule was tightened to require an
# adjacent failure word (e.g. ``capacity exceeded``, ``billing error``).
# This map encodes the new contract: when the parity test feeds these
# two specific legacy fragments, anchor them to the minimum stderr the
# new classifier accepts. All other literals feed unchanged.
_PARITY_TEST_INPUT_OVERRIDE: dict[str, str] = {
    "billing": "billing error",
    "capacity": "capacity exceeded",
}


def _resolve_test_input(legacy_fragment: str) -> str:
    """Map a legacy tuple literal to the minimum stderr the new
    classifier accepts. Identity for everything except the two
    intentionally-narrowed bare tokens above."""
    return _PARITY_TEST_INPUT_OVERRIDE.get(legacy_fragment, legacy_fragment)


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
        # The legacy helpers did `pattern in error_text.lower()`, so the
        # bare fragment was the minimum stderr the legacy helper accepted.
        # The new classifier intentionally narrows two bare tokens
        # (`capacity`, `billing`) to require an adjacent failure word —
        # see _PARITY_TEST_INPUT_OVERRIDE above. For those two we feed
        # the minimum-anchored form; everything else feeds unchanged.
        test_input = _resolve_test_input(pattern)
        result = classify(test_input)
        expected = _FALLBACK_STATUSES[platform]
        assert result in expected, (
            f"{platform} legacy fragment {pattern!r} (fed as {test_input!r}) "
            f"classified to {result!r}, not in expected fallback set "
            f"{expected}; step 5 helper rewrite would change CLI-chain "
            f"behaviour"
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
        # Same anchoring as Class 1 for the two narrowed bare tokens.
        test_input = _resolve_test_input(pattern)
        helper_says_exhausted = self._classify_via_helper(platform, test_input)
        classifier_says_exhausted = (
            classify(test_input) in _FALLBACK_STATUSES[platform]
        )
        assert helper_says_exhausted == classifier_says_exhausted, (
            f"{platform} parity drift on {pattern!r} (fed as {test_input!r}): "
            f"helper={helper_says_exhausted}, classifier-in-fallback-set="
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
