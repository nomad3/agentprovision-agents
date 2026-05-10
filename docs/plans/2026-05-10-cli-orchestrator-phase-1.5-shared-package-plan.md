# Phase 1.5 — Shared `packages/cli_orchestrator/` Package (retrospective plan)

**Status:** ✅ Merged via PR #337 (commit `afeb8cb2`) on 2026-05-10
**Branch:** `feat/cli-orchestrator-phase-1.5-shared-package` (deleted post-merge)
**Closes:** Phase 1's **I-1 deviation** (cross-runtime import isolation)

> Retrospective. Planning-time Plan-agent output (sub-agent `a796b11c`) is consolidated below.

## Why this phase exists

Phase 1 left a known structural gap: `apps/code-worker/workflows.py` couldn't `from app.services.cli_orchestrator import classify` because the worker container mounts only `./apps/code-worker:/app` — `apps/api/app` isn't on its `PYTHONPATH`. The worker's three `_is_*_credit_exhausted` helpers therefore stayed pattern-matching against local tuples instead of delegating to the new canonical classifier. **Two source-of-truth paths** in production = the duplicate-code bug the design's §0 principle was specifically meant to fix.

Phase 1.5 moves the canonical classifier to a shared location both runtimes import.

## Architectural decisions

### Package layout — option **(D) flat directory namespace package on `PYTHONPATH`**

Considered:
- **(A)** `packages/cli_orchestrator/` with `pyproject.toml` + `pip install -e` — heaviest ceremony, version-bump dance, layer cache thrashing
- **(B)** Keep at `apps/api/app/services/cli_orchestrator/`, mount into worker via docker-compose volume — couples worker container image to a sub-tree of apps/api; Phase 2's adapters in worker would point arrows backwards
- **(C)** `apps/shared/cli_orchestrator/` — `apps/` is the runtime namespace; libraries don't belong there
- **(D)** *(chosen)* `packages/cli_orchestrator/` at repo root, no `pyproject.toml`, just `__init__.py` + submodules. Both Dockerfiles `COPY packages/cli_orchestrator /app/cli_orchestrator`. Both `conftest.py` prepend `<repo-root>/packages/` to `sys.path` for tests.

Why D wins: zero pip ceremony, layer cache stays warm, `packages/` is the universally-recognised "shared library" namespace, Phase 2's worker-side adapters can `from cli_orchestrator import classify` symmetrically without arrows pointing at `apps/api`.

### Migration choice — shim, not hard move

Two viable shapes:
- **Hard move:** delete `apps/api/app/services/cli_orchestrator/`, recreate at `packages/cli_orchestrator/`, sweep all `from app.services.cli_orchestrator import …` callers
- **Shim:** *(chosen)* leave `apps/api/app/services/cli_orchestrator/` as 4 re-export modules (`from cli_orchestrator import *` + explicit private-symbol re-exports for tests reaching for `_Rule`, `_STDERR_RULES` etc.)

Why shim: 174 existing tests stay green by construction. Phase 2's chat hot path migrates callers off the shim at its own pace.

### Worker-side legacy tuples — keep one phase as DEAD CODE

The `CLAUDE_CREDIT_ERROR_PATTERNS` / `CODEX_…` / `COPILOT_…` tuples at `apps/code-worker/workflows.py:106-146` are now **unused at runtime** (helpers delegate to `classify`). They stay one phase because:
1. `test_workflow_definitions.py:74-77` has legacy attribute tests
2. `test_credit_exhausted_parity.py` corpus pulls them live
3. Phase 2 deletes them in one focused commit once parity is green

## File tree after Phase 1.5

```
packages/cli_orchestrator/                     NEW — canonical home
├── __init__.py
├── status.py                                  (moved verbatim)
├── classifier.py                              (moved verbatim)
└── redaction.py                               (moved verbatim)

apps/api/app/services/cli_orchestrator/        SHIM — re-exports
├── __init__.py                                (4-line shim)
├── status.py                                  (1-line shim)
├── classifier.py                              (1-line shim + private re-exports)
└── redaction.py                               (1-line shim)

apps/code-worker/
├── workflows.py                               MODIFIED — 3 helpers delegate
├── Dockerfile                                 MODIFIED — COPY packages/cli_orchestrator
└── tests/
    ├── conftest.py                            MODIFIED — sys.path insert for /repo/packages
    ├── test_cli_orchestrator_import.py        NEW — cross-runtime smoke
    └── test_credit_exhausted_parity.py        NEW — legacy corpus ≡ classifier
```

`docker-compose.yml` + `docker-compose.prod.yml` build context widened from `./apps/<service>` to `.` (repo root) for both api + code-worker + orchestration-worker. `.github/workflows/docker-desktop-deploy.yaml` change-detection paths updated so `packages/cli_orchestrator/` edits trigger rebuilds.

## Issues caught in layered review

| Layer | Catch |
|---|---|
| Plan-agent self-review | I-A test-monkeypatch patch-target drift (14 specific sites in 3 test files); I-B circular import resolved via lazy `from workflows import` inside executor function bodies; I-C `_opencode_sessions` dict identity preservation across re-export aliases |
| Implementation self-review | The 14 patch sites was actually 26 — plan undercounted. Honored higher-priority "zero behaviour change" constraint and updated all 26. |
| Independent review | **I-A**: bare `billing` / `capacity` over-broadening on apps/api chat hot path. Legacy tuples included these as bare substrings; safe on worker stderr (always context-rich) but `cli_platform_resolver.classify_error` now feeds chat hot path, where bare `"capacity planning meeting"` would trigger 10-min cooldown. Tightened to require adjacent failure word (`capacity[\s_-]?(exceeded\|exhausted\|reached\|error\|limit)`). Added 8-case parametrize in `test_phase_1_5_widened_fallback_surface` documenting the new chat-side fallback-trigger surface. |
| Final pass | Bare `forbidden` token pinned with one parametrize case (Phase 2 narrows naturally via per-adapter routing) |

## Lessons

1. **Plan-agent recon undercount risk.** The I-A enumeration of patch sites was 14; reality was 26. Future plans of this shape: run a fresh `grep -rn 'monkeypatch.setattr(wf\.' tests/` against the actual codebase at planning time, not memory.
2. **Bare-token regexes are platform-asymmetric.** What works on subprocess stderr (always failure context) over-fires on chat content (often benign user prose). Anchor them.
3. **The shim pattern preserves blast radius.** Hard-moving 174 tests' worth of imports during a runtime cutover would have been the Phase 2 cutover blast radius doubled. Shim defers the sweep to its natural commit.
