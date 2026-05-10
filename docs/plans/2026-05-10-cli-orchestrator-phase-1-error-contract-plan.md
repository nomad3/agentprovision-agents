# Phase 1 — Error Contract + Redaction (retrospective plan)

**Status:** ✅ Merged via PR #336 (commit `0e14e24b`) on 2026-05-09
**Branch:** `feat/cli-orchestrator-phase-1-error-contract` (deleted post-merge)
**Design source:** [`2026-05-09-resilient-cli-orchestrator-design.md`](./2026-05-09-resilient-cli-orchestrator-design.md) §2 + §5 + §7

> Retrospective note. The planning-time Plan-agent output (sub-agent `a43c9459`) lived in the task transcript and isn't preserved verbatim here. This file consolidates what was actually planned and shipped, so future contributors can read the "what + why" without scrubbing the merged commits.

## Goal

Land the design's normalised `Status` enum + a single `classify(stderr, exit_code, exc) -> Status` function + a redaction primitive, with **zero behaviour change**: the existing pattern tuples in `apps/code-worker/workflows.py` and `cli_platform_resolver.classify_error` become thin delegators to the new classifier and continue returning the same string labels they always did.

## Hard constraints (Phase 1 ship gate)

(a) Every classification-table row in design §2 has a named test.
(b) Redaction property test + negative-redaction property test pass.
(c) `grep -r classify_error apps/` returns the **same set of call sites** pre/post.
(d) `grep -r _is_*_credit_exhausted apps/` returns the same call sites.
(e) NO Phase 2+ surface (no ProviderAdapter, FallbackPolicy, ResilientExecutor, recursion gate, ExecutionMetadata, observability metrics, agent-token, MCP work, webhook events).

## What landed

| Module | LOC |
|---|---|
| `apps/api/app/services/cli_orchestrator/__init__.py` | 35 |
| `apps/api/app/services/cli_orchestrator/status.py` | 61 |
| `apps/api/app/services/cli_orchestrator/classifier.py` | 399 |
| `apps/api/app/services/cli_orchestrator/redaction.py` | 253 |
| `apps/api/tests/cli_orchestrator/test_classification.py` | 216 (17 named §2-row cases + 17 legacy-label cases + 3 edge cases) |
| `apps/api/tests/cli_orchestrator/test_redaction.py` | 519 (per-rule + concatenated-leak + property + 5 rule-8a boundary + json-structural + cleanup_codex_home + SENSITIVE_ENV_KEYS) |

**Wrapper sites delegated:**
- `apps/api/app/services/cli_platform_resolver.py:198` — `classify_error` body replaced with delegating wrapper; legacy regex constants (`_QUOTA_PATTERNS`, `_AUTH_PATTERNS`, `_MISSING_CRED_PATTERNS`) kept + marked DEPRECATED
- `apps/code-worker/workflows.py:106,119,133` — pattern tuples reworded `PHASE 1.5 — replace via shared cli_orchestrator package; canonical for worker runtime until then` (the worker side couldn't actually delegate due to cross-runtime import isolation — that's the I-1 deviation Phase 1.5 closes)

**174 / 174 tests green.**

## Issues caught in layered review

| Layer | Catch |
|---|---|
| Plan-agent self-review | `Status.NEEDS_AUTH` cardinality (legacy maps to two labels: `"auth"` + `"missing_credential"`); cross-runtime import risk; Phase 2 test leak (`test_no_fallback_on_auth.py` depends on FallbackDecision); env-var sanitiser scope |
| Implementation self-review | I-1 cross-runtime import isolation hits — STOP-and-reported per plan, didn't improvise a shared-package layout |
| Independent review | DEPRECATED markers misleading on worker side (the patterns are LIVE not dormant); negative-redaction property test corpus gap (never exercised rule 8a `<trigger>:<value>` shape on benign config-shaped prose); design-doc drift (rules 3 + 7 narrowing in implementation didn't match §2 table — added footnotes ¹ ²) |
| Final pass | Pinned bare `forbidden` contract before merge (one-line parametrize case) |

## Lessons for future phases

1. **Cross-runtime import isolation is real.** `apps/code-worker` can't naively import from `apps/api/app/services/...`. Surfaced as I-1 here; closed by Phase 1.5 (shared `packages/cli_orchestrator/`).
2. **DEPRECATED markers must be honest.** If marked code is still load-bearing (as the worker pattern tuples were), the marker reads as "safe to delete" to a hurried reader. Use forward-pointing TODOs (`PHASE 1.5 — replace …; canonical until then`) instead.
3. **Negative-redaction tests need adversarial corpora.** Pure-prose property generators that never produce `:` or `=` after a trigger word will never exercise rule 8a's actual gate. The independent reviewer caught this; commit fixup added 5 boundary cases pinning the accepted over-redaction.
