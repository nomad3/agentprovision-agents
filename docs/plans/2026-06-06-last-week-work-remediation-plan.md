# Last-Week Work Remediation Plan (2026-05-29 → 2026-06-06)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Read the "Collision-safety & worktree strategy" section before touching any file** — Codex is actively working in this repo.

**Goal:** Close the 51 verified findings from the multi-agent audit of last week's ~60 PRs — covering drift, unfinished/scaffolded work, technical debt, AI slop, and broken architectural patterns — without colliding with Codex's in-flight Luna Tauri / alpha-CLI work.

**Architecture:** Findings are grouped into independent **workstreams**, each shippable as its own worktree + PR (chained where they touch shared files). Three execution tracks: **A** = free to fix off `main`; **B** = lives on unmerged feature branches (fix in that PR); **C** = Codex's live domain (coordinate, do not touch directly).

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy, Temporal), Rust (Tauri, alpha CLI crates), React (CRA), Helm/Docker-Compose, Postgres+pgvector.

---

## How this plan was produced

A 13-agent ultracode workflow audited the window across 9 thematic areas (Luna desktop-control, trusted-teammate engines, WhatsApp, monitor/orchestration, code-worker CLI, GitHub SSH, Vet OS, landing, Claudia bridge) plus 4 cross-cutting sweeps (infra drift, architecture conformance, DB/migration integrity, tests+slop). Raw findings: **75 → 60 deduped → 60 verified → 51 confirmed real** (9 rejected as already-fixed or non-existent-on-`main`). Each confirmed finding was adversarially re-verified against the actual code in `HEAD`.

**Severity profile:** 1 blocker · 3 high · 15 medium · 32 low. 8 findings sit in the Codex live zone (Track C).

**Verified-and-cleared (no action — recorded so they aren't re-audited):**
- F02 (all CI jobs non-blocking) — true but the dedicated blocking Postgres job in F03 is the real fix.
- F06 (CODEX_MODEL missing from `*-local.yaml`) — drift exists but harm doesn't (folded into F05/the deploy-script root cause).
- F13/F33/F34/F58 (vet echo parser bugs) — target file does **not** exist on `main`; lives only on unmerged `vet-os/central-os-foundation`. Belongs to that PR's review (see Track B).
- F18 (signed-envelope nonce gate untested) — false in `HEAD`; #807 shipped the gate **and** 233 lines of live tests in the same commit (`test_desktop_command_lifecycle.py`).
- F37 (no `rl_experience` for desktop-control) — grep-true but `publish_session_event` audit spine exists; downgraded to a Track-C nicety, not a gap.
- F59 (git fail-fast depends on image envs) — both code facts hold; the positive auth path is present. Covered indirectly by F01/F15.

---

## Collision-safety & worktree strategy (READ FIRST)

The repo is being mutated by a Codex agent **while this plan runs**. During the audit alone, `HEAD` moved from `codex/luna-signed-envelope-gate` → `codex/alpha-chat-async-send`. There are ~20 active worktrees. Treat the tree as moving.

**Three zones:**

| Zone | Paths | Rule |
|---|---|---|
| 🔴 **Codex live (uncommitted now)** | `apps/agentprovision-cli/**`, `apps/agentprovision-core/**`, `.github/workflows/luna-client-build.yaml`, `docs/cli/**` | **Never touch.** Codex has these dirty right now (alpha-chat async send). |
| 🟠 **Codex domain (recently churning)** | `apps/luna-client/**`, `apps/api/app/services/desktop_control_service.py`, `apps/api/app/api/v1/desktop_control.py`, `apps/mcp-server/src/mcp_tools/desktop_control.py`, `apps/api/app/models/desktop_command*.py`, desktop migrations **158, 160, 161** | **Track C — coordinate, do not edit.** All 8 codex-zone findings live here. Hand to Codex or queue until its desktop-control + alpha-CLI streams settle. *(Migration 159 is `chat_sessions.owner_user_id` — not desktop-control; WS8-F28 only mirrors its index into `models/chat.py`, a read-only reference, no Track-C edit.)* |
| 🟢 **Free** | everything else: `apps/code-worker/cli_executors/*.py` (Python — *not* Codex's Rust CLI), `apps/api/app/services/*` (non-desktop), `helm/`, `scripts/`, `apps/web/`, `.github/workflows/tests.yaml` | **Track A — isolated worktree off `main` per workstream.** |

**Mechanics (every Track-A workstream):**
1. `git fetch origin main`
2. `git worktree add -b fix/<workstream-slug> <path> origin/main` — always branch off **fresh `origin/main`**, never off the current (Codex) checkout.
3. Chain branches when two workstreams touch the same file (e.g. `main.py` is touched by WS3-F10 and WS6) — branch the second off the first per the `feedback_chain_pr_branches` rule.
4. One PR per workstream, assigned to `nomade`. Run code review through Codex pinned to gpt-5.5 + Luna per the standing review rules.
5. **Before starting a workstream, check `git worktree list`** — several sibling worktrees already exist for related work (`feat/github-ssh-worker`, `feat/vet-practice-provisioner`, `feat/vet-landing-page`). Rebase/coordinate rather than duplicate.

**This plan document itself** was authored in `agentprovision-agents-wt/remediation-plan` off `origin/main`, leaving the main checkout's Codex changes untouched.

---

## Findings → workstream map

| WS | Title | Track | Findings | Top sev |
|---|---|---|---|---|
| **WS1** | Per-turn credential isolation (all executors) | A | F01, F52 | **blocker** |
| **WS2** | Infra drift: deploy script + helm/compose mirroring | A | F05, F07, F08, F04, F60 | high |
| **WS3** | Monitor/orchestration starvation: real fix + hardening | A | F12, F43, F09, F10, F11, F42, F23, F53 | medium |
| **WS4** | Trusted-teammate engines: wire or honestly label | A | F20, F21, F22, F57, F27, F56 | medium |
| **WS5** | GitHub SSH: CLI-agnostic wiring + hardening | A | F16, F15, F26, F41, F44 | high |
| **WS6** | WhatsApp shutdown robustness | A | F24, F39, F40 | medium |
| **WS7** | Landing i18n parity + cleanup | A | F31, F49, F47, F45, F46, F48 | low |
| **WS8** | CI/test-gate hardening | A | F03, F28, F30 | medium |
| **WS9** | Claudia bridge: collision-safe + kernel decision | A | F54, F55 | low |
| **WS10** | Code-worker CLI misc | A | F51 | low |
| **TB** | Vet OS echo extractor (unmerged branch) | B | F14, F32 | high |
| **TC** | Codex desktop-control coordination | C | F17, F19, F25, F29, F35, F36, F38, F50 | medium |

---

## Execution order

1. **WS1** (blocker — cross-tenant credential bleed). Do first, alone.
2. **WS2** + **WS5** + **TB** (the three highs). WS5-F16 depends on WS1's shared env helper → chain WS5 off WS1. TB goes into the vet branch PRs.
3. **WS3, WS4, WS6, WS8** (medium batch — parallelizable, mind the `main.py` chain between WS3 and WS6).
4. **WS7, WS9, WS10** + remaining lows (cleanup batch).
5. **TC** runs in parallel as a coordination thread with Codex — never blocks Track A.

---

# TRACK A — Free to fix off `main`

## WS1 — Per-turn credential isolation for all executors (BLOCKER)

**Why:** `execute_chat_cli` writes a **process-global** `os.environ["GITHUB_TOKEN"]` (the current tenant's vault OAuth token) and mutates the shared workspace git remote + `gh auth login`. The worker runs activities in a `ThreadPoolExecutor(max_workers=10)`, so two concurrent chat turns race: tenant B overwrites the global, then tenant A's `codex`/`gemini`/`copilot` git op authenticates as tenant B. `claude.py` is already immune (`_apply_git_credential_env` re-fetches per-turn); the other three are not. **This is a cross-tenant credential bleed + tenant-isolation violation.**

**Files:**
- Modify: `apps/code-worker/cli_runtime.py` (new shared helper)
- Modify: `apps/code-worker/workflows.py:1186-1208` (drop the `os.environ` writes + shared remote/gh mutation)
- Modify: `apps/code-worker/cli_executors/codex.py:94`, `gemini.py:114`, `copilot.py:56,99`
- Modify: `apps/code-worker/cli_executors/claude.py:44-72,401-402,504-521` (hoist helper out; remove vestigial inits — F52)
- Test: `apps/code-worker/tests/test_credential_isolation.py` (new)

- [ ] **Step 1 — Write the failing concurrency test.** Two tenants with distinct vault tokens; interleave `codex`/`gemini`/`copilot` env construction on the threadpool; assert each subprocess env carries **only** its own tenant's `GITHUB_TOKEN`/`GH_TOKEN` and that `os.environ` is never written.

```python
def test_concurrent_turns_do_not_share_github_token(monkeypatch):
    # tenant A -> tokenA, tenant B -> tokenB via patched _fetch_github_token
    # run two build_base_env() calls interleaved; assert envA["GITHUB_TOKEN"]==tokenA
    # and "GITHUB_TOKEN" not in os.environ
```

- [ ] **Step 2 — Run it; expect FAIL** (`build_base_env` undefined / token leaks).
- [ ] **Step 3 — Add `cli_runtime.build_base_env(task_input)`** that does `env = os.environ.copy()`, fetches `_fetch_github_token(task_input.tenant_id)`, applies it to **`env` only** via a hoisted `apply_git_credential_env(env, token)` (moved from `claude.py:44-72`), and returns `(env, cleanup)`. Also hoist `apply_git_ssh` call here (sets up WS5-F16).
- [ ] **Step 4 — Repoint executors:** `codex.py`/`gemini.py`/`copilot.py` start from `build_base_env(task_input)` instead of a bare `os.environ.copy()`; remove `copilot.py:56` `os.environ.get("GITHUB_TOKEN")` prefetch.
- [ ] **Step 5 — Strip the global mutation** in `workflows.py`: delete `os.environ["GITHUB_TOKEN"]=` (1188), the `os.environ.pop` (1208), and replace the shared `git remote set-url`/`gh auth login --with-token` (1190-1199) with per-subprocess env auth (no shared WORKSPACE remote/gh-config writes). Remove the now-duplicated `_fetch_github_token`+`_apply_git_credential_env` block from `claude.py:504-521`; delete vestigial `interactive_submit=None`/`interactive_answer_dir=None` (claude.py:401-402) — **F52**.
- [ ] **Step 6 — Run the concurrency test + existing `test_execute_chat_cli.py`; expect PASS.**
- [ ] **Step 7 — Commit** (`fix(code-worker): per-turn GitHub credential env for all executors — close cross-tenant token bleed`).

**Collision:** Files are Python `code-worker` executors — **not** Codex's Rust CLI. Safe off `main`. WS5 chains off this branch.

---

## WS2 — Infra drift: deploy script + helm/compose mirroring

**Root cause first (F05).** `scripts/deploy_k8s_local.sh:139-157` applies **only** the `*-local.yaml` overlay (single `-f`) for api/mcp/orchestration/web/code-worker. So every env the team mirrored into the **base** helm values last week (`#757/#758/#764/#766/#767`) is dead on the K8s path. This is why F07 and F08 manifest. Fix the loader, then the values.

**Files:** `scripts/deploy_k8s_local.sh:139-157`; `helm/values/agentprovision-api-local.yaml`, `agentprovision-code-worker-local.yaml`, `agentprovision-code-worker.yaml`; new `helm/charts/microservice/templates/claude-sessions-pvc.yaml`; `helm/charts/microservice/templates/deployment.yaml`; delete `docker-compose.prod.yml`.

- [ ] **F05 — Chain base+local in the deploy script.** Change the five app-service upgrades to pass both files (`-f base.yaml -f local.yaml`), matching the embedding/memory-core pattern (later `-f` wins). `helm template` each pair; confirm the four hardening keys render and no local override (image tag, `pullPolicy: Never`, replicas) is lost. Commit.
- [ ] **F08 — API hardening into `agentprovision-api-local.yaml`.** Add `terminationGracePeriodSeconds: 180`, `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN: "10"`, `DISABLE_MONITOR_CONTINUE_AS_NEW: "1"` (mirror base `agentprovision-api.yaml:242-248` + compose). Commit.
- [ ] **F07 — Blank `ANTHROPIC_API_KEY` for the K8s code-worker.** Add an explicit `env: [{name: ANTHROPIC_API_KEY, value: ""}]` to **both** `agentprovision-code-worker-local.yaml` (new `env:` block) and `agentprovision-code-worker.yaml` (append to existing list). `env:` overrides `envFrom:` in the pod spec — verify `deployment.yaml` emits `env:` before `envFrom:`. Prevents OAuth/Max tenants being hijacked onto Console billing (the #762 failure). Commit.
- [ ] **F04 — `claude-sessions` RWX PVC.** Add `claude-sessions-pvc.yaml` mirroring `workspaces-pvc.yaml` (gated on `.Values.claudeSessions.enabled && not existingClaim`); add volume+mount in `deployment.yaml` (mountPath `/home/codeworker/.claude`); api chart provisions (RWX), code-worker chart sets `claudeSessions.existingClaim` and drops `/home/codeworker` from `tmpDirs`. Replicate to `*-local.yaml`. Fix the false "Mirrored in Helm" comment in `docker-compose.yml`. Commit.
- [ ] **F60 — Delete `docker-compose.prod.yml`** (unreferenced, `.env.production` missing, comments falsely claim "prod"); remove the stale breadcrumb in `docs/plans/2026-05-10-cli-orchestrator-*`. Commit.

**Collision:** none. Per the global "replicate to helm, git, terraform" rule, also confirm terraform needs no mirror (it's AWS/EKS, prod-disabled — note that explicitly in the PR).

---

## WS3 — Monitor / orchestration starvation: real fix + hardening

The four hotfixes (#754/#755/#757/#758) are band-aids by their own admission; memory write-back reliability currently depends on `DISABLE_MONITOR_CONTINUE_AS_NEW=1` staying on, which keeps monitors dark (F43).

**The real fix (F12, scope L) — dedicated memory queue:**
- [ ] Introduce `agentprovision-memory` Temporal queue; new `apps/api/app/workers/memory_worker.py` registering `PostChatMemoryWorkflow` + `CoalitionWorkflow` + their activities, run as a separate process.
- [ ] Point `apps/api/app/memory/dispatch.py:33` (and the Coalition dispatch site) at the new queue; remove those workflows/activities from `orchestration_worker.py`.
- [ ] Replicate the new worker into `docker-compose.yml` + new `helm/values/agentprovision-memory-worker.yaml` + chart deployment (no-drift rule).
- [ ] **F43** — Once the queue decouples memory from monitors, flip the default and ship a re-enable path; acceptance criteria = monitors can run without starving memory.

**Hardening (small, can land first):**
- [ ] **F10 — Plug kill-switch leaks.** Extract `_monitors_disabled()` helper; call it from `main.py:320` (startup_proactive), `main.py:254` (teams reconcile — early-return before `create_task`), `oauth.py:625` (google auto-start). In `teams_monitor.py` before `continue_as_new()` add the activity-based check (env reads are non-deterministic in workflow code).
- [ ] **F09 — Audit ALL monitor activities for missing `retry_policy`.** `learn_from_media_workflow.py` activities at 321/383/392/459/473/497/511 have none (only 287 does); add bounded policies. Broaden `_wrap` to catch `ConnectError`, not just `HTTPStatusError`.
- [ ] **F11 — Fit retries inside the 60s budget.** Set both `generate_sync` calls in `local_inference.extract_knowledge_with_prompt_sync` (491,504) to `timeout=25.0` so `25+3+25+overhead ≈ 55s < 60s`.
- [ ] **F42 — Typed kill-switch result.** `dynamic_executor.py:239` returns a raw dict; return `DynamicWorkflowResult(status="stopped_by_killswitch", ...)`.
- [ ] **F23 — JSONB scalar-containment bug (RL human approve/reject).** `apps/api/app/workflows/activities/feedback_activities.py:333,360` `proposed_policy.contains(platform)` compiles to `@>` and never matches a bare scalar. Replace with `proposed_policy["platform"].astext.like(f"{platform}%")` (handles the `claude`→`claude_code` short/full mismatch). Add a regression test. **This is the #773 bug class.**
- [ ] **F53 — Slop.** `auto_quality_scorer.py:170` drop the redundant `if cost_usd else "0.0000"` guard (already a guaranteed float).

**Collision:** `main.py` is also touched by WS6 → chain WS6 off WS3, or land WS3's `main.py` changes first.

---

## WS4 — Trusted-teammate engines: wire or honestly label

PRs #771/#792/#805 shipped read-side endpoints + render helpers but **no runtime producers** — the engines are islands. Decide per engine: wire a producer, or explicitly annotate "substrate-only; consumer in PR N" so acceptance criteria aren't implied-satisfied.

- [ ] **F20 — ReflectionStep producer.** `GET /luna/reflection-steps` returns `[]` forever. Add `build_reflection_step(...)` in `reflection.py`; call `reflection_io.write_reflection_step(...)` at high-friction sites — co-locate with the metacog hooks in `cli_session_manager.py` (~:1977 `write_prediction` / :2051 `write_observation`) and on the code-worker PR-creation path. Keep best-effort.
- [ ] **F21 — Source-grounding consumer.** `source_grounding.py` pure functions have zero callers; the "every claim is grounded" safety invariant is unmet. Wire `render_claim_for_user`/`summarize_grounding` into the chat-response path, **or** annotate substrate-only.
- [ ] **F22 — Handoff-card consumer.** `handoff_card.py` render fns unused. Wire into the code-worker PR-body builder (`workflows.py` ~:1066) when a task carries handoff metadata, **or** annotate substrate-only.
- [ ] **F57 — Schema validation.** `schemas/reflection.py:96` `ReflectionStep.__post_init__` — mirror `HandoffCard`'s identity loop: require non-empty `tenant_id`/`agent_id`/`session_id`; make list non-emptiness consistent.
- [ ] **F27 — Slop.** `reflection_io.py:97-99` comment claims a "Postgres JSON-contains pushdown" the read path deliberately does NOT do (post-filters in Python) — rewrite to match reality.
- [ ] **F56 — Slop.** `reflections.py:3-4` drop the stale "Den UI" reference (Den was removed).

**Collision:** none. (`cli_session_manager.py` is shared infra — coordinate if another stream touches it.)

---

## WS5 — GitHub SSH: CLI-agnostic wiring + hardening  *(chain off WS1)*

**Why high:** A `gemini_cli`/`copilot_cli` tenant pastes an SSH key in `/integrations`, sees a green fingerprint, but the agent's clone still fails — `GIT_SSH_COMMAND` is only set in `claude.py:521`/`codex.py:122`. UI says "configured", behavior is broken. The `cli_runtime.py:36-37` docstring falsely claims all executors inherit it.

- [ ] **F16 — Hoist SSH into the shared base env.** With WS1's `build_base_env` in place, fold `apply_git_ssh` + `_fetch_github_ssh_key` into it so every executor inherits SSH per-turn; drop the duplicated blocks from `claude.py:510-521` and `codex.py:113-122`; fix the `cli_runtime.py` docstring. Add a test asserting `gemini`/`copilot` envs carry `GIT_SSH_COMMAND`.
- [ ] **F15 — Fail-fast host-key bake.** `Dockerfile:223` `ssh-keyscan ... 2>/dev/null || true` makes a failed keyscan ship an empty `known_hosts` → all SSH clones fail at runtime. Drop `|| true` + add `grep -q '^github.com '` assertion (or pin published fingerprints via heredoc + `ssh-keygen -F`).
- [ ] **F26 — Don't decrypt the key on status polls.** `ssh_key.py:165-171` `ssh_key_status` calls `retrieve_credentials_for_skill` (full private-key decrypt) just to check presence. Return `{"present": True}` from the existence check and fetch only the fingerprint metadata row.
- [ ] **F41 — TMPDIR-agnostic scrub.** `cli_runtime.py:317` `_GHSSH_PATH_RE` hardcodes `/tmp/ghssh_` but `mkdtemp` honors `$TMPDIR`; broaden the regex to match the `ghssh_` basename regardless of leading dir.
- [ ] **F44 — Atomic-ish save.** `ssh_key.py:140-162` `save_ssh_key` does revoke + two independent commits; swap order so the fingerprint is written **after** the key fails safe (mid-crash → `present=False`, not a usable key with no fingerprint).

**Collision:** none with Codex. **Check the existing `feat/github-ssh-worker` worktree first** — rebase onto it rather than duplicate.

---

## WS6 — WhatsApp shutdown robustness  *(chain off WS3 for `main.py`)*

- [ ] **F24 — Reclaim orphaned `chat_jobs`.** `os._exit(0)` on drain timeout (`main.py:424-431`) can leave `chat_jobs.status='running'` forever (the #769 hung-CLI scenario). Add `chat_jobs.reclaim_orphaned_jobs(db, older_than_seconds=660)` (`UPDATE ... SET status='failed', error='reclaimed after restart' WHERE status IN ('running','queued') AND created_at < NOW() - interval`) and a fire-and-forget startup hook (mirror the Teams reconcile pattern). Key off `created_at` (no `started_at` column) at the 660s turn-lifetime ceiling so live turns aren't falsely failed.
- [ ] **F40 — Gate `os._exit` on the real condition.** `main.py:424-425` gates only on `IN_DOCKER`; non-docker uvicorn shutdown re-introduces the ~180s neonize hang. Gate on `whatsapp_service.NewAClient is not None` (set iff neonize lazy-loaded).
- [ ] **F39 — Reset `_draining`.** `whatsapp_service.py:2516` sets `_draining=True` but never resets; wrap the drain body in try/finally and reset in `finally` (safe — `shutdown()` already cleared clients).

**Collision:** `main.py` shared with WS3-F10 → branch WS6 off the WS3 branch (chained PR).

---

## WS8 — CI / test-gate hardening

- [ ] **F03 — Make the JSON-pushdown bug class catchable.** The SQLite test shim (`conftest.py` `JSONB→JSON @compiles`) hides the #773 bug; the Postgres `api_integration` job is `continue-on-error + || true`. (a) Split out a **small dedicated blocking** job that runs only Postgres-semantics regressions (`test_metacog_io`, `test_reflection_io`, the F23 test) against pgvector **without** `continue-on-error`; add to branch protection via `gh api`. (b) Add a smell lint (extend `scripts/smell/`) that fails when `.contains(` is called on a column declared `Column(JSON` (generic, not JSONB). Document the rule in `conftest.py`.
- [ ] **F28 — Single-source the index.** `migration 159` indexes `chat_sessions.owner_user_id` but the ORM model lacks it. Add `__table_args__ = (Index("idx_chat_sessions_owner_user_id", "owner_user_id", postgresql_where=text("owner_user_id IS NOT NULL")),)` to `models/chat.py`.
- [ ] **F30 — Regression test for the #754 None-format fix.** `auto_quality_scorer.py:123` shipped with no guard. Add a test in `test_routing_rollout_pipeline.py` (mirror the mock setup at 189-214) asserting the scorer survives a `None` field without raising in the f-string.

**Collision:** none. F29 (desktop models constraints) is the DB-integrity sibling but is codex-zone → Track C.

---

## WS7 — Landing i18n parity + cleanup

- [ ] **F31 — i18n the Alpha landing.** All 8 `apps/web/src/components/marketing/alpha/*.js` are hardcoded English; Spanish browsers get a half-translated page. Add an `alpha` namespace to `en/landing.json` + `es/landing.json` (hero/engines/metrics/differentiators/realityLedger/commands/platformPower) and wire `useTranslation('landing')`.
- [ ] **F49 — Prune orphaned i18n keys.** Delete the 8 dead top-level sections (`lakehouse, architecture, roadmap, testimonials, featuresGrid, logos, ai, memory`) from both `landing.json` files; keep the 10 live keys.
- [ ] **F47 — De-dup the apex URL.** New `apps/web/src/components/marketing/constants.js` exporting `APEX_REGISTER`/`APEX_SIGNIN`; replace the 4 hardcoded call sites in `AlphaHero.js`/`AlphaLandingPage.js`.
- [ ] **F45/F46/F48 — Slop.** `AlphaCommands.js:2` "Eight-up grid"→"a grid" (renders 7); `AlphaRealityLedger.js:49,98` replace `dangerouslySetInnerHTML`+`&rsquo;` with a literal `'`; `AlphaCommands.test.js:13-15` replace the copy-pasted agent_policy comment with an accurate one.

**Collision:** web churn — **check `feat/vet-landing-page` worktree** before starting.

---

## WS9 — Claudia bridge

- [ ] **F54 — Slugify collision.** `claudia_bridge.py:262` `_write_outbox` silently overwrites when distinct `task_id`s slugify to the same filename. Reject meaningless ids (`slug == 'task'`) and append a short hash suffix to guarantee uniqueness.
- [ ] **F55 — Kernel decision (D5).** It's an off-kernel parallel delegation channel with no `alpha <verb>`. Pragmatic: add a docstring note declaring it an intentional **local-only operator utility** deliberately not wired into the kernel — make the decision conscious and documented.

**Collision:** none.

---

## WS10 — Code-worker CLI misc

- [ ] **F51 — Per-turn Codex model override dropped.** `task_input.model` is ignored on the chat path (`codex.py:54`, `workflows.py:1314,1482,1510-1512`). Either honor it, or (preferred if the connect-flow selection isn't imminent) delete the dead `model` param + precedence comment and collapse to `os.environ.get("CODEX_MODEL") or "gpt-5.5"`.

**Collision:** none. Can fold into WS1's PR if convenient.

---

# TRACK B — Unmerged feature branches (fix in their PR, not `main`)

These files do **not** exist on `main`; do not create them there. Route fixes into the owning branch's open PR.

- [ ] **F14 (high) — Echo extractor is dead code.** `apps/api/app/services/vet/echo_extractor.py` (branch `vet-os/central-os-foundation`) has no caller; the Cardiac Report Generator still uses unverified LLM PDF extraction, and the "unconditional human_approval before send" safety floor is unimplemented (`needs_review` computed, nothing consumes it). In that branch: insert a deterministic extraction step (MCP tool calling `extract_from_pdf_bytes`) before `generate_cardiac_report` in `workflow_templates.py:221-290`, feed structured measurements into the draft, and add an unconditional `human_approval` step before send. **Note:** the rejected parser bugs F13/F33/F34/F58 also live in this file — fold them into the same branch review.
- [ ] **F32 (low) — Soften provisioner framing.** `provisioning/vet_manifest.py:53` (branch `feat/vet-practice-provisioner`) implies a shipped deterministic-extraction guarantee while F14 is unwired; reword the persona copy.

---

# TRACK C — Codex desktop-control coordination (DO NOT edit directly)

All 8 findings touch Codex's live domain (🟠/🔴 zones). **Action = coordinate**, not edit. Hand this list to Codex (or queue a single coordinated worktree once Codex's desktop-control + alpha-CLI streams settle). F36 in particular overlaps with what Codex is building *right now* (alpha CLI).

| ID | Sev | Finding | Note for Codex |
|---|---|---|---|
| **F17** | med | Desktop command down-channel (enqueue) has **no production caller**; MCP observation tools only hit the always-deny stub | Re-point `mcp_tools/desktop_control.py:60` at `/internal/commands` (the claimable down-channel); add completion polling. F35 sequences after this. |
| **F36** | low(↑) | Desktop-control has **no `alpha <verb>` kernel path** — violates the kernel principle | Add an `alpha desktop` subcommand group (`apps/agentprovision-cli/src/commands/desktop.rs`). **Overlaps Codex's current alpha-CLI work — raise directly.** |
| **F25** | med | Shell/device binding reads from **in-memory** `luna_presence_service._presence_store` — non-deterministic under multi-replica API | Back presence with Redis (already a dep); keep signatures stable so `desktop_control_service.py` needs no change. |
| **F19** | med | `get_active_app`/`track_active_app` **permanently denied** on macOS — automation probe hardcodes `unknown` | Implement the real `AEDeterminePermissionToAutomateTarget` probe in `permissions.rs`, or drop `automation_system_events` from `ActiveApp.required_grants()`. |
| **F38** | low | Pre-existing **multi-user-tenant sessions** permanently 403 from desktop control (`owner_user_id` NULL) | Add a one-time "claim session ownership" action or a clear client message. |
| **F35** | low | Stale "down-channel unavailable / not_implemented" messaging | After F17 lands, update the messaging to the real state. |
| **F29** | low | `desktop_commands`/`desktop_command_events` models omit migration-158 CHECK constraints + indexes (ORM↔DB drift) | Mirror migration 158 into both models (whatsapp_session_backup precedent). |
| **F50** | low | Redundant function-local `import hashlib` in `desktop_control_service._device_for_user_shell` | Delete the local import (module-level one at line 5 covers it). |

**Coordination mechanism:** post this table to Codex via the established review channel (dashboard Codex-5.5 turn / Luna), or open a tracking issue. Do not branch off these files until Codex signals the desktop-control surface is stable.

---

## Definition of done

- [ ] WS1 merged (blocker closed; concurrency test green).
- [ ] WS2/WS5/TB highs merged.
- [ ] Medium batch (WS3/WS4/WS6/WS8) merged; monitors re-enablable without starving memory (F12/F43).
- [ ] Low cleanup (WS7/WS9/WS10 + remaining) merged.
- [ ] Track C handed to Codex with confirmation it's owned.
- [ ] Each PR reviewed via Codex-5.5 + Luna; every finding either fixed or consciously deferred with a written reason (per `feedback_address_all_review_findings`).
- [ ] No drift: every compose change mirrored to helm; terraform staleness explicitly acknowledged as acceptable (prod-disabled).
