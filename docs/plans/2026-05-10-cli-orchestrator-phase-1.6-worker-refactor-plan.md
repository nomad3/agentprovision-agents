# Phase 1.6 — Worker CLI-Runtime Refactor (retrospective plan)

**Status:** ✅ Merged via PR #338 (commit `d3ccfc22`) on 2026-05-10
**Branch:** `feat/cli-orchestrator-phase-1.6-worker-refactor` (deleted post-merge)
**Soft prerequisite for Phase 2** (worker-side ProviderAdapter implementations)

> Retrospective. Planning-time Plan-agent output (sub-agent `ab299610`) is consolidated below.

## Why this phase exists

Phase 2's worker-side adapters wrap `_run_cli_with_heartbeat` + `_execute_*_chat` helpers that lived as **private symbols inside the 2,318-line `apps/code-worker/workflows.py`**. Importing private symbols across runtime boundaries is fragile, and any worker test importing a Phase 2 adapter would pull in all 2,318 lines of activity definitions.

Phase 1.6 hoists the worker's CLI runtime + per-platform chat executors into clean public modules, in preparation for Phase 2.

## Architectural decisions

### Package layout — option **(A) flat** over single-package

```
apps/code-worker/
├── workflows.py                                # 2,318 → 1,559 lines (-32.7%)
├── cli_runtime.py                              # NEW — leaf module (~120 lines)
└── cli_executors/                              # NEW — per-platform executors
    ├── __init__.py
    ├── claude.py                               # ~110 lines
    ├── codex.py                                # ~95 lines
    ├── gemini.py                               # ~180 lines
    ├── copilot.py                              # ~210 lines
    └── opencode.py                             # ~110 lines
```

`cli_runtime.py` has one concept (heartbeat-on-activity-thread Popen primitive + safe-snippet sanitiser). `cli_executors/` is naturally a package — five sibling modules. Phase 2's adapters live alongside as `cli_orchestrator_adapters/` with a clean `adapter → executor → runtime` arrow.

### Cycle break — lazy imports inside executor function bodies

`workflows.execute_chat_cli` dispatches to executors. Executors need `_fetch_claude_token`, dataclasses (`ChatCliInput`, `ChatCliResult`), constants (`WORKSPACE`, `CLAUDE_CODE_MODEL`) from `workflows`. That's a cycle.

Resolution: `from workflows import _fetch_claude_token, ChatCliResult, …` happens **inside each executor function body**, not at module top. Side benefit: every existing `monkeypatch.setattr(wf, "_fetch_claude_token", ...)` test continues to work because Python re-resolves the lazy import at call time and `setattr` updates the same module attribute.

### Re-export object identity preservation

`workflows.py` re-imports the new public names back under their old `_`-prefixed aliases:

```python
from cli_runtime import (
    run_cli_with_heartbeat as _run_cli_with_heartbeat,
    safe_cli_error_snippet as _safe_cli_error_snippet,
)
from cli_executors.claude import execute_claude_chat as _execute_claude_chat
# … etc.
from cli_executors.opencode import (
    execute_opencode_chat as _execute_opencode_chat,
    _execute_opencode_chat_cli,
    _opencode_sessions,
    OPENCODE_OLLAMA_URL,
    OPENCODE_MODEL,
    OPENCODE_PORT,
)
```

This preserves **object identity** — `wf._opencode_sessions is cli_executors.opencode._opencode_sessions` so tests mutating `wf._opencode_sessions["tenant-x"]` mutate the live dict. Pinned by `test_workflows_legacy_aliases_still_resolve`.

### What stayed in `workflows.py`

- All `@activity.defn` and `@workflow.defn` classes (`execute_code_task`, `execute_chat_cli`, `ChatCliWorkflow`, `CodeTaskWorkflow`, etc.)
- All dataclasses (`CodeTaskInput`, `ChatCliInput`, `ChatCliResult`, `ProviderCouncilInput`, etc.)
- `_run`, `_run_long_command` — code-task-only path, different invariant, NOT a Phase 2 concern
- `_fetch_*`, `_prepare_*`, `_INTEGRATION_NOT_CONNECTED_MESSAGES`, `_build_allowed_tools_from_mcp` — credential/integration helpers; moving them would force a wide test-side rewrite
- The `*_CREDIT_ERROR_PATTERNS` tuples (Phase 1.5 dead code; Phase 2 deletes)

## Implementation order — 7 commits

1. Hoist `run_cli_with_heartbeat` + `safe_cli_error_snippet` to `cli_runtime.py` + 6 patch retargets in `test_run_helpers.py` `TestRunCliWithHeartbeat`
2. Hoist `_execute_claude_chat` to `cli_executors/claude.py` + 4 patch retargets in `test_execute_chat_cli.py`
3. Hoist `_execute_codex_chat` to `cli_executors/codex.py` + 3 patch retargets in `test_chat_cli_helpers.py::TestExecuteCodexChat`
4. Hoist `_execute_gemini_chat` to `cli_executors/gemini.py` (no test edits needed)
5. Hoist `_execute_copilot_chat` to `cli_executors/copilot.py` (no test edits needed)
6. Hoist opencode chat surface (5 names: `execute_opencode_chat`, `_execute_opencode_chat_cli`, `_opencode_sessions`, `OPENCODE_*` × 3) + 7 patch retargets in `test_chat_cli_helpers.py::TestExecuteOpencodeChat` (`wf.httpx` → `cli_executors.opencode.httpx`; `wf.subprocess` → `cli_executors.opencode.subprocess`)
7. Add `tests/test_cli_runtime_imports.py` smoke (4 tests: cli_runtime public surface, per-platform imports, package re-export shape, workflows legacy aliases preserve object identity)

Each commit ships green tests at its gate. Per-commit progression: 248 → 248 → 248 → 248 → 248 → 248 → 252.

## Issues caught in layered review

| Layer | Catch |
|---|---|
| Plan-agent self-review | I-A test-monkeypatch patch-target drift (14 sites named in 3 test files); I-B circular import resolved via lazy imports; I-C `_opencode_sessions` dict identity |
| Implementation self-review | I-A enumeration was incomplete — actual count was **26 patch sites**, not 14. Honored zero-behaviour-change constraint over the plan's specific count. Plus logger namespace shift for `cli_executors/gemini.py` + `cli_executors/opencode.py` (now log under `cli_executors.<platform>` instead of `workflows`) — documented in module docstrings, behaviour unchanged |
| Independent review | One Important non-blocker: 5 dead `ChatCliInput` lazy imports in executor function bodies (signatures dropped; type annotation use is gone). Folded before opening PR — 5-line cleanup |
| Final pass | "Ready to merge." 252/252 green, byte-identical function bodies verified by spot-diff, object identity preserved across all 8 legacy aliases |

## Lessons

1. **Pure-refactor PRs are deceptively dangerous.** "Zero behaviour change" doesn't mean "zero code-path change"; the test-monkeypatch surface drifts because patch targets follow the moved symbol. Must enumerate every `monkeypatch.setattr` site and update in lockstep with the move.
2. **Lazy imports are a legitimate cycle-break tool in Python.** They're idiomatic for breaking module-load cycles AND have the side benefit of preserving test monkeypatches that re-resolve at call time. Use them deliberately, not as a "this is a hack" workaround.
3. **Re-exports preserve object identity.** `from X import Y as Z` gives `module.Z is X.Y` — leveraged here to keep `wf._opencode_sessions` mutable across the alias boundary.
