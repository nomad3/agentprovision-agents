# Test Suite Modernization — Multi-Session Plan

**Date:** 2026-05-03
**Owner:** Simon (nomade)
**Status:** **Shipped — all 8 phases + 5 follow-up phases merged on main.** See "Outcome" at the bottom for the post-rollout snapshot.
**Companion plan:** None — execution log lives in the per-phase PR descriptions and in the "Outcome" section below.

## 1. Goal

Bring every app in the monorepo to a state where:

1. The full test suite **collects and runs cleanly** (no hard import-time DB / network requirements in default runs).
2. **Coverage is measured** per app and reported on every PR.
3. **Coverage is high enough to be useful** — target ~80% line coverage on Python services, ~70% on React/Tauri React, ~70% on Rust services. Not a hard gate; a ratchet we move forward each session.
4. **Tests run in parallel on GitHub Actions, non-blocking.** Agents (and humans) get fast feedback when their change broke a test or feature, but a red test does *not* block merging — the user explicitly relies on agentic AI to triage and fix breaks downstream.

## 2. Why non-blocking CI

The user runs many parallel coding agents. Hard gates on tests would create deadlocks where one agent's stale test blocks another agent's correct change. Instead:

* CI **always reports** status (pass/fail + coverage delta).
* PRs can merge while red. Failures appear on the merged commit and are visible to the next agent or to the human.
* RL / quality scoring already penalises agents that ship regressions, so this is a known feedback path — CI is a **signal, not a gate**.

## 3. Scope — eight phases, executed across sessions

| Phase | Owns | Stack | Today | Target this round |
|---|---|---|---|---|
| 0 | `.github/workflows/tests.yaml` | GH Actions | none | Matrix workflow, parallel, non-blocking, coverage artefacts + PR comments |
| 1 | `apps/api` | Python / FastAPI / pytest | 517 tests, 5 collection errors (psycopg) | Fix collection, mark integration tests, pytest-cov, ~80% on services + routes |
| 2 | `apps/web` | React / CRA / Jest | 20 tests (wizard + marketing) | Add tests for top pages + components, jest --coverage, ~70% |
| 3 | `apps/mcp-server` | Python / FastMCP | 8 tests | Per-module suites for 24 tool modules / 81 tools, ~80% |
| 4 | `apps/code-worker` | Python + Node | **0 tests** | Bootstrap pytest, mock Temporal + CLI subprocess, ~60–70% |
| 5 | `apps/embedding-service` + `apps/memory-core` | Rust / tonic gRPC | minimal | `cargo test` units for handlers + pipeline, cargo-llvm-cov, ~70% |
| 6 | `apps/luna-client` | Tauri 2 (Rust + React) | minimal | jest/vitest for React, src-tauri Rust units for audio/window/tray, ~60% |
| 7 | `apps/device-bridge` | TBD (investigate) | TBD | Minimal coverage of IoT bridge + camera helpers |

Each phase ships its own PR. Each PR is independent — Phase 0 has no dependency on the rest, and any Phase 1–7 PR can land in any order once Phase 0 has measurement infra in place.

## 4. Phase 0 — Parallel non-blocking CI (executed first, this session)

### Workflow shape

`.github/workflows/tests.yaml` — runs on `pull_request` and `push: [main]`:

* `jobs.api` — Python 3.11, pip cache, run `pytest --cov=app --cov-report=xml -m "not integration"` in `apps/api`.
* `jobs.web` — Node 20, pnpm install, run `npm test -- --ci --coverage --watchAll=false` in `apps/web`.
* `jobs.mcp` — Python 3.11, run `pytest --cov=src --cov-report=xml` in `apps/mcp-server`.
* `jobs.code-worker` — Python 3.11, run `pytest --cov=. --cov-report=xml` in `apps/code-worker` (no-op until Phase 4 lands).
* `jobs.rust` — `cargo test --workspace` over `apps/embedding-service` and `apps/memory-core`, plus `cargo-llvm-cov` for coverage.
* `jobs.luna-client` — Node + Rust, runs jest + `cargo test` in `src-tauri`.
* `jobs.device-bridge` — Node, runs `npm test` (no-op until Phase 7).

All jobs use `continue-on-error: true` and `if: always()`. A summary job (`jobs.report`) aggregates artefacts into a single sticky PR comment showing per-app status + coverage delta. **No `required` status checks** — that's the non-blocking part.

### Triggering rules

* `paths` filters per job so we don't run all suites on every change. e.g. `jobs.api.if: contains(changed-files, 'apps/api/')`.
* On `push: [main]`, **all jobs always run** so we always have a coverage baseline.

### Coverage publication

Coverage XML uploaded as workflow artefact. PR comment posts a markdown table of `app · prev% · new% · Δ`. No external service (no Codecov dependency unless the user later wants it).

## 5. Per-phase cross-cutting rules

These apply to every Phase 1–7 PR and are repeated in each phase's plan doc.

1. **Touch only test files + test config + minimal CI tweaks.** Production code changes are allowed only as surgical bug fixes uncovered while writing tests, called out explicitly in the PR body.
2. **Each phase is one PR.** Branch name `tests/phase-<n>-<scope>`, assigned to `nomade`, no AI co-author footer.
3. **Coverage measured + reported in PR description.** Before/after numbers from local runs.
4. **Slow / external-dep tests are marked, not deleted.** Pytest gets `@pytest.mark.integration`. Jest gets a `__integration__` directory excluded from default jest config. Default CI run skips them; a separate manual workflow runs them.
5. **No mocks of internal modules unless they hit the network.** We mock Temporal client, Ollama HTTP, Anthropic SDK, Google APIs, OpenAI SDK, Postgres (only when not available locally), Redis, and subprocess CLI calls. We do **not** mock our own services / repositories / schemas.
6. **Helm/Terraform drift check.** When test scaffolding adds env vars or services, replicate into Helm + Terraform per project rule.

## 6. What "done" looks like for each phase

* Phase 0: PR comment shows per-app status + coverage on the next PR after merge. CI runs in <8 minutes wall-clock end-to-end.
* Phases 1–3: full suite green locally and in CI; coverage for that app at or above target; integration markers on tests requiring real services; PR description shows before/after coverage.
* Phase 4: `apps/code-worker` has a working `pytest` command and at least a thin smoke suite (>= 50% coverage), with mocked Temporal + CLI subprocess.
* Phase 5: `cargo test` runs in CI for both Rust services; coverage measured via cargo-llvm-cov.
* Phase 6: jest/vitest passes for `apps/luna-client/src/`; `cargo test` passes inside `src-tauri/`. Tauri build itself remains the responsibility of the existing release workflow — *not* this plan (per user rule: never build Tauri locally).
* Phase 7: device-bridge stack identified, minimal smoke suite + CI job wired into Phase 0's matrix.

## 7. Risks / open questions

* **Other parallel agents may rewrite source while we add tests.** Mitigation: prioritise stable modules (models, services, utils) over fast-moving UI / route handlers in each phase.
* **Coverage targets are aspirational, not guaranteed in one pass per app.** If a phase only gets to 50%, we ship that and ratchet next session.
* **device-bridge stack is unknown.** Phase 7 starts with investigation — may bump scope or get deferred.
* **Postgres-dependent API tests** can be made unit-runnable via `pytest-postgresql` or a lightweight `sqlite + sqlalchemy` fixture, but the service uses pgvector — those queries need a real Postgres. Plan: keep them under `@pytest.mark.integration`, run them only on a dedicated CI job that boots a Postgres service container.
* **Tauri builds** are signed and run on CI only — we will not run `npm run tauri build` in the test workflow.

## 8. Execution order this session

1. Land Phase 0 (CI matrix + reporting) in its own worktree → PR.
2. Land Phase 1 (apps/api) in its own worktree → PR. Both PRs can be open simultaneously.
3. Stop. Subsequent phases run in later sessions, one (or two parallel) at a time.

## 9. Out of scope for this plan

* End-to-end browser tests (existing `scripts/e2e_test_production.sh` covers this and stays as-is).
* Performance / load tests.
* Mutation testing.
* Visual regression for the marketing site.
* Migration to Vitest from Jest in `apps/web` — only if Phase 2 finds CRA/jest blockers.

## 10. Outcome — what shipped (2026-05-03 → 2026-05-06)

Sixteen PRs merged across the original eight phases plus five follow-up phases plus two cleanup PRs. CI matrix is live and non-blocking on every PR with ~2-3 minute wall-clock.

### Phase log

| Phase | PR | Headline |
|---|---|---|
| 0 — CI matrix + spec | #259 | 8 parallel jobs, non-blocking, sticky aggregate PR comment |
| 1 — apps/api | #261 | 456 → 630 tests / 28 → 30% / **0 source bugs** |
| 2 — apps/web | #266 | 60 → 255 tests / 4 → 21% (~5x) |
| 3 — apps/mcp-server | #272 | 26 → 435 tests / 17 → 62% / **2 real bugs fixed** (`resolve_tenant_id` × 6 sites) |
| 4 — apps/code-worker (bootstrap) | #275 | 0 → 118 tests / 0 → 52% |
| 5 — Rust services | #274 | 0 → 39 tests across embedding + memory-core |
| 6 — apps/luna-client | #277 | 57 React + 22 Rust tests / **1 real bug fixed** (invalid Tauri capability blocking `cargo build` everywhere) |
| 7 — apps/device-bridge (bootstrap) | #278 | 0 → 32 tests / 0 → 89% |
| Cleanup | #282 | 10 review nits + **2 real bugs fixed** (duplicate `_fetch_claude_token`, `Optional[str]` typing on credit-check helpers) |
| Mop-up | #283 | mark `test_gesture_bindings` as integration (UUID/SQLite incompat) |
| 1.5 — api integration CI | #310 | new `api_integration` job with pgvector service container, `app/` 7% → 31% on integration job |
| 2.5 — web pages stretch | #311 | 297 → 387 tests, 23.65% → 35.17% (page-level coverage for Chat/Agents/Detail/Integrations/Memory) |
| 4.5 — code-worker stretch | #312 | 126 → 178 tests, workflows.py 47% → 92%, package 52% → 90%; real `WorkflowEnvironment` integration tests |
| 5.5 — memory-core handlers | #313 | 23 → 38 tests; introduced `MemoryStore` trait + `PgStore` + `FakeStore`; all 4 gRPC handlers now unit-testable |
| 6.5 — luna-client larger surfaces | #314 | 57 → 105 React tests; ChatInterface, MemoryPanel, NotificationBell, WorkflowSuggestions covered |

### Real bugs found and fixed (5)

1. **mcp-server**: `resolve_tenant_id(tenant_id, ctx)` called with two args at six sites (`memory_continuity.py` × 5 + `supermarket.py` × 1). The function takes one arg — every invocation TypeErrored at runtime. Fixed in #272.
2. **luna-client**: `core:webview:allow-get-webview-window` in `src-tauri/capabilities/default.json` is not a valid Tauri 2.10.3 permission. The capability validator rejects unknown permissions, breaking `cargo build` for every contributor. Fixed in #277.
3. **code-worker**: duplicate `_fetch_claude_token` definitions in `workflows.py` (second wins, first is dead). Fixed in #282.
4. **code-worker**: missing `Optional[str]` typing on three credit-check helpers that silently mismatched on `None` input. Fixed in #282.
5. **api**: `test_gesture_bindings.py` failed at collection on SQLite because it imports models with Postgres `UUID` columns. Marked as integration in #283.

### CI infrastructure now in place

* `.github/workflows/tests.yaml` runs 9 parallel jobs on every PR (api unit, api integration with pgvector, web, mcp, code-worker, rust × 2, luna-client, device-bridge).
* Path filters skip jobs that don't touch their app. On `push: main`, all jobs run for a baseline.
* Sticky `tests-matrix` PR comment aggregates per-app pass/fail status.
* All jobs use `continue-on-error: true` and **no required check** — tests are signal, not gate.
* `pytest-timeout=60s` on api integration job to prevent runner exhaustion from hung async fixtures.

### Test counts at end of rollout

| App | Before phase 0 | After phase 6.5 |
|---|---|---|
| apps/api | 456 (with broken collection) | 630+ (unit) plus integration job |
| apps/web | 60 | 387 |
| apps/mcp-server | 26 | 435 |
| apps/code-worker | 0 | 178 |
| apps/embedding-service + memory-core | 0 | 16 + 38 = 54 |
| apps/luna-client | minimal | 105 React + 22 Rust = 127 |
| apps/device-bridge | 0 | 32 |
| **Total** | **~542** | **~1,843** |

### What is still deferred (not blocking)

* Mutation testing / visual regression / load tests — out of scope from §9 above.
* `apps/web` pages still at 0% (WorkflowsPage, SkillsPage, SettingsPage, Layout, IntegrationsPanel) — natural follow-up.
* `apps/api/app/api/` route handlers via integration job: 30+ integration tests need fixture cleanup before hitting their honest coverage ceiling.
* Phase 6 commit message has wrong Tauri-version attribution (`2.11` vs locked `2.10.3`); the fix itself is correct, just the rationale on the merged commit. Stuck in git history.

### Companion follow-up tasks (in `~/.claude/projects/.../memory/MEMORY.md` if needed)

For the next session, the natural next move is `apps/web` continued page coverage (WorkflowsPage / SkillsPage / SettingsPage / IntegrationsPanel are the four remaining 0% surfaces). Everything else is in good shape.

