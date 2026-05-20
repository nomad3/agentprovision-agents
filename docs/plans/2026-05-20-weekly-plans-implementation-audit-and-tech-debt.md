# Weekly plans implementation audit + tech debt — 2026-05-13 → 2026-05-20

Date: 2026-05-20
Owner: Claude Code (autonomous audit; operator review pending)
Status: Audit complete. Recommendations queued for operator triage.
Reviewer: Luna (to be dispatched after operator review)

---

## Why this doc exists

Operator directive 2026-05-20 (~22:30 Chile time, going to bed):

> *"create plans using the pattern in docs plans and make sure all plans we have been working have been fully implemented for the whole last week work, make a code review and detect technical debt"*

A subagent surveyed every plan in `docs/plans/` dated 2026-05-13 through 2026-05-20, cross-referenced against the merged-PR list in the same window, grepped for tech-debt markers in the changed files, and spot-checked the 3 largest implementations. The body below is that audit, ready for operator triage tomorrow morning.

This complements the more focused 2026-05-19 audit doc (`docs/plans/2026-05-19-pr-merge-plan-and-tech-debt-audit.md`) by extending the window to a full week and re-checking what shipped during the post-merge-plan period.

---

## 1. Plans surveyed

**35 plan documents filed during the window:**

| Date | Plans |
|------|-------|
| **2026-05-13** | alpha-agent-view-and-goal-recipes, ap-cli-differentiation-roadmap, readme-alpha-cli-section-design |
| **2026-05-14** | laptop-sentinel-design |
| **2026-05-15** | alpha-control-center-ide-shell-design, alpha-control-plane-design, alpha-control-plane-tier-0-1-plan |
| **2026-05-16** | codex-mcp-tool-access-fix, codex-mcp-transport-mismatch-research, dashboard-split-pane-spec-doc-viewer, gemini-cli-oauth-exitcode-41, oauth-reconnect-token-format-mismatch, terminal-full-cli-output, terminal-vscode-style-redesign, workstation-cloud-memory-sync |
| **2026-05-17** | async-chat-result-pattern-design, code-worker-tenant-home-cap-design, gemini-cli-picker-and-disk-pressure-session, password-recovery-email-design |
| **2026-05-18** | alpha-cli-delegation-pattern, alpha-review-consensus, alpha-run-real-dispatch, cli-integration-catalog, docker-image-shrink-and-latency, higgsfield-end-to-end-validation, landing-copy-alpha-as-os, skill-creator-framework-port, whatsapp-api-research |
| **2026-05-19** | emotions-engine-prototype-design, luna-tauri-habit-tracker-design, pr-merge-plan-and-tech-debt-audit, session-handoff, skill-eval-temporal-parent-pattern-adr, stale-pr-triage, teamwork-engine-design |
| **2026-05-20** | whatsapp-waha-migration-design, weekly-plans-implementation-audit-and-tech-debt (this doc) |

---

## 2. Implementation status per plan

| Plan | Spec scope | Shipped? | Open follow-ups |
|------|-----------|----------|-----------------|
| **alpha-run-real-dispatch** (#573, #593) | Single/multi-provider real Temporal dispatch + per-tenant default | ✅ Phase 2 live; default-provider lookup landed (#593) | 7: quota-aware fallback (#304), timeout plumb, agent_id prop, council merge, naked alpha run, events stream |
| **emotion-engine** (#586, #592, #600) | PAD vector state + appraisal (tool_outcome, tool_failure, peer_signal) + tool_failure wire-in | ✅ Phase 1 + part of Phase 2 shipped | Phase 3: user_signal classifier, agent_id attribution, per-tenant RLCF tuning |
| **skill-creator framework** (#546, #579, #580) | Framework port: Phase 1 schema, Phase 2 eval runner, Phase 3 analyzer | ✅ All three phases shipped | Phase 4: eval-viewer SSE feed + parent-workflow completion tracking (task #294) |
| **alpha-review** (#574, #581) | Consensus loop: start/status/reply/list/watch | ✅ Shipped + dispatch fix | LLM-based finding adjudication (council merge) queued |
| **whatsapp hardening** (#596, #598, #599, #600, #601) | Heartbeat + session lock + stable-reset + property-access fixes + disable/logout SQLite purge | ✅ 5 fixes shipped this session | WAHA long-term migration designed (#597); Phase 1 implementation pending |
| **whatsapp WAHA migration** (#597) | Long-term protocol fix for repeated re-pair bugs | ❌ Design only (PR #597 design merged); 5 phases queued | Awaits operator approval to start Phase 1 |
| **teamwork-engine** (#589) | Social Protocol primitive — role contracts + norms + affect-aware coordination | 🟡 Design merged; PR A (schema+reads) opened tonight as #602 | PR B (write paths + bootstrap), PR C (operator write verbs + SupervisorMediationWorkflow) |
| **luna-tauri-habit-tracker** (#585) | Vision-based desk habit tracker on Tauri | 🟡 Design merged | v1 impl awaits operator scope approval |
| **skill-eval temporal parent** (ADR only) | Parent-workflow completion tracking for eval artifacts | ❌ No implementation; task #294 pending | Blocks eval-viewer artifact write + status machine; current rows stay at `queued` after dispatch |
| **alpha control center** (#578) | v0.7.5 IDE shell design + consensus-loop subcommand | ✅ CLI docs shipped; impl live as alpha subcommand | VSCode-style pane splits deferred (#567 spec-only) |
| **dashboard split pane** | Right-pane file tree + doc viewer composition | 🟡 Design spec filed; FileTreePanel landed in separate track | Depends on landing ResizableSplit + FileViewer (not in this window) |
| **terminal full-cli output** | Replace stub with live CLI transcript stream | 🟡 Design filed; root cause diagnosed | 3 blockers: worker→API plumbing, session_id propagation, subprocess draining |
| **docker image shrink** (#566) | Remove whisper + sentence-transformers from API | ✅ Phase A shipped (3.95→3.27 GB); Phase B partial (code-worker) | Phase D — move OAuth handshake out of api — pending task #295 |
| **higgsfield e2e** (#572) | Glue for chat-driven generation | ✅ Shipped | Token refresh worker still TODO (task #298, blocked on Higgsfield API verification) |
| **landing page redesign** (#543, #146) | Reposition Alpha as agent OS | ✅ Shipped | — |
| **async-chat-result** (#570) | async-job pattern to kill Cloudflare 524 | ✅ Shipped | — |
| **cli integration catalog** (#553, #559, #569) | Wave 1 + Wave 2 CLI executors + Higgsfield | ✅ Shipped | Higgsfield commercial-terms verification still pending (task #300) |
| **chat-session Luna-prefix fix** (#595) | Default-agent picks Luna* not 'Root Cause Analyst'; HH:MM disambiguator | ✅ Shipped today | — |
| **emotion engine experiment report** (#594) | Luna awareness + relational register audit | ✅ Shipped as docs/report/ | — |
| **session handoff** (#582) | Day-end handoff doc + role-split pin | ✅ Shipped | — |
| **stale PR triage** (#590) | 13-PR disposition recommendations | ✅ Shipped | Operator-driven closure of 5 high-confidence stale PRs still pending |
| **PR merge plan** (#584) | Durable record of the 5-PR merge sequence | ✅ Shipped | — |
| **other design-stage plans** (~10) | Various: control plane Tier 0/1, session handoff, password recovery, sentinel, etc. | Mixed | See ranked next-actions below |

---

## 3. Tech debt surfaced

### BLOCKER

- **`apps/api/app/api/v1/emotion.py:16`** — Import path regression from PR #586 (used `app.api.dependencies` instead of `app.api.deps`). Hot-fixed in PR #591 after ~55 min api downtime. **Mitigation already shipped:** new test `apps/api/tests/test_router_imports.py` in PR #592 enforces import-path correctness in CI by importing `app.api.v1.routes` and walking the router graph. Same class of bug cannot recur unnoticed.

### IMPORTANT

- **`apps/api/app/services/cli_session_manager.py:1413, 1194, 1132, 660`** — Four bare `except Exception` clauses marked `# noqa: BLE001` in the emotion-layer integration (#592, #600). Never crash chat to protect availability, but mask real errors at debug log level only. Phase 3 should add Prometheus counters + structured logging for silent emotion-layer failures.

- **`apps/api/app/services/emotion_engine_io.py:349`** — `record_session_tool_failure` falls back to random UUID when `agent_id` is None, leaving `affect_vector` without agent-of-record. TODO(phase-3) already documented in the helper docstring. Per-agent affect analytics blind to failures from `cli_session_manager` until plumbed.

- **`apps/api/app/services/skill_creator/eval_runner.py:54-58`** — Parent-workflow pattern deferred (task #294, ADR at `docs/plans/2026-05-19-skill-eval-temporal-parent-pattern-adr.md`). Today `skill_eval_runs` rows stay at `queued` after dispatch; completion tracking relies on Temporal history inspection, not DB state machine. Blocks eval-viewer artifact write and UX status reporting.

- **`apps/code-worker/cli_runtime.py:158-169`** — `proc.communicate()` buffers entire CLI output. Terminal streaming design (#568) blocked until subprocess switches to line-reader threads; cannot emit `cli_subprocess_stream` events incrementally.

- **`apps/api/app/services/whatsapp_service.py`** — Five property-vs-method bugs fixed in 4 sequential PRs over 2 days (PR #596, #598, #599, #601). Each fix is correct but the repeated pattern suggests fuzzy boundary between neonize `NewAClient` property semantics and callable behavior. **Mitigation candidate:** import neonize type stubs into dev environment + run `pyright --strict apps/api/app/services/whatsapp_service.py` in CI, OR add per-method thin wrappers that shield the rest of the codebase from neonize API instability. The WAHA migration (PR #597) eliminates this class entirely.

### NIT

- **`apps/api/app/services/emotion_engine.py`** — Tuning constants hard-coded (`TOOL_OUTCOME_PLEASURE_GAIN=0.30`, etc.). Phase 3 RLCF should learn per-tenant offsets; no issue now, note for future.

- **`docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`** — Seven Phase-3 extensions documented inline (`--merge council`, `--timeout`, `--providers` quota-aware fallback). No code debt, but signals incomplete CLI surface.

- **`apps/api/migrations/140_skill_eval_iteration_runs.sql`** — Status taxonomy (`queued`, `running`, `ok`, `error`, `timeout`) kept Python-side rather than DB constraint. Maintainable but loses schema-layer safety.

---

## 4. Code-review spot-checks

### Emotion Engine Phase 1-2 (PR #586 + #592, ~500 LOC)

**File:** `apps/api/app/services/emotion_engine.py`

**Risk:** Pure-function appraisal loop is clean and well-tested. Four hard-coded tuning constants and no observability into edge cases (clamping, decay convergence). Production will ship 3-axis PAD vectors to Blackboard + `affect_baseline` persistence with no metrics on how often decay triggers or how much clamping happens.

**Fix:** Add Prometheus counters for `emotion_appraise_clamp_events` (per-axis) and `emotion_decay_convergence_ticks` histogram. Wire into Luna's monitoring dashboard in Phase 4.

### Skill-Creator Phase 2-3 (PR #579 + #580, ~1.2k LOC)

**File:** `apps/api/app/services/skill_creator/eval_runner.py`

**Risk:** Dispatch pattern changed from daemon-thread-in-request to direct `Client.start_workflow` call (PR #581). New pattern is safer BUT leaves `skill_eval_runs` in `queued` indefinitely — the row never transitions to terminal status until the Phase-3 parent-workflow lands. Row-level audit trail is broken until then.

**Fix:** Either (a) implement task #294 (parent workflow) which is the documented permanent fix, or (b) add a cron sweep `periodic_skill_eval_completion_sync` that queries Temporal for finished workflows and backfills `skill_eval_runs` status + artifacts. Needed before eval-viewer ships.

### WhatsApp Hardening (PR #596 + #598-#601, ~200 LOC total)

**File:** `apps/api/app/services/whatsapp_service.py:1427, 1431, 1486, 1490, 1494`

**Risk:** Five 1-line property-vs-method bugs fixed in 4 sequential PRs over 2 days. Each fix is correct but the pattern is fuzzy boundary between neonize property semantics and callable behavior. No type hints on neonize return values means Python IDE tooling can't catch these at edit time.

**Fix:** Import neonize type stubs into dev environment; run `pyright --strict apps/api/app/services/whatsapp_service.py` in CI to surface untyped property calls. Or add thin wrapper methods (`def is_connected_safe(self): return self._client.is_connected`) to shield internal calls from neonize API instability.

---

## 5. Recommended next actions (ranked)

1. **Land skill-eval parent-workflow (task #294, Phase 3)** — Unblocks eval-viewer artifact write, eval-runner completion tracking, and dashboard integration. Required before any `SKILL_EVAL_ENABLED=true` feature flag flip.

2. **Fix subprocess streaming (blocker on terminal redesign)** — Replace `proc.communicate()` with threaded line-reader in `apps/code-worker/cli_runtime.py`. Unblocks `cli_subprocess_stream` event producer and full-transcript display in the terminal card.

3. **Start WAHA migration Phase 1** (PR #597 design awaits approval) — Sidecar + AbstractWhatsAppBackend interface + NeonizeBackend wrapping existing code. No behaviour change for existing tenants, but lays the substrate that eliminates the entire whatsmeow property-confusion class.

4. **Harden whatsapp property handling** — Type-check `whatsapp_service.py` via pyright or add wrapper methods. Prevents future property-vs-method confusion as neonize evolves. Lower priority than WAHA migration since #597 makes this moot.

5. **Backfill `skill_eval_runs` status** — Cron sweep to sync Temporal workflow completion into the table until parent-workflow lands. Allows eval-viewer to read status from DB rather than polling Temporal.

6. **Add emotion-engine observability** — Prometheus counters for appraise-clamp and decay convergence. Needed to tune per-tenant RLCF constants in Phase 3 without blind guessing.

7. **Plumb agent_id through tool_failure wire-in** — Closes the TODO(phase-3) in `emotion_engine_io.py:349`. Restores per-agent affect attribution.

8. **Operator-driven closures from #590 stale PR triage** — 5 high-confidence closures (`#472, #473, #316, #431, #451`) ready to close per the audit's disposition recommendations. ~5 minutes.

9. **Higgsfield commercial-terms verification (task #300)** — Operator action item; blocks scaling Higgsfield past ~10 tenants per `2026-05-18-cli-integration-catalog.md` L109/156/158.

10. **Defer alpha control plane Tier 0.1** — Design doc filed but blocks on other control-center primitives; not a launch blocker for v0.7.5 or v0.8. Queue for v0.9.

---

## 6. What this audit does not cover

- **Operational health of running services** — separate dashboard (Den / Prometheus) is the right surface.
- **External integrations** (Higgsfield ToS, Gemini quota, WhatsApp rate-limit) — operator action items, not code debt.
- **The stale PR backlog older than 2026-05-13** — already triaged in PR #590.
- **Production incident postmortems** — separate docs/report/ tree.

## 7. Process meta-note

The 2-day rapid-iteration cadence (35 plans, ~20 PRs in 7 days) is delivering a lot but also accumulating "Phase N follow-ups" faster than they're being resolved. The week's tech-debt list has 4 IMPORTANT items and 3 NITs — manageable, but the trend is upward. **Recommendation:** before opening Phase 1 of WAHA, close items #1, #2, #5, #6, #7 from §5 above. That's ~3-5 days of focused cleanup that brings the platform back to a sustainable debt-to-feature ratio for the launch push.

---

## Related

- Prior audit: `docs/plans/2026-05-19-pr-merge-plan-and-tech-debt-audit.md` (narrower window, more granular per-PR view).
- Stale PR triage: `docs/plans/2026-05-19-stale-pr-triage.md`.
- WAHA design: `docs/plans/2026-05-20-whatsapp-waha-migration-design.md`.
- Emotion engine design: `docs/plans/2026-05-19-emotions-engine-prototype-design.md`.
- Teamwork Engine design: `docs/plans/2026-05-19-teamwork-engine-design.md`.

## Next actions for the operator

1. Review this audit, prioritise the §5 ranked list against your launch timeline.
2. Approve WAHA Phase 1 (#597) if the ranked sequencing is acceptable.
3. Close the 5 high-confidence stale PRs from #590's triage.
4. Decide on Higgsfield commercial-terms outreach (#300).
5. Approve emotions Phase 3 scope (per-agent attribution + observability).

When operator finishes triage, dispatch this doc to Luna for an
independent read.
