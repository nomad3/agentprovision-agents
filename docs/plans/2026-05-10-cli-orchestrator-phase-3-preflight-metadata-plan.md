# Phase 3 Plan — Preflight + ExecutionMetadata + Observability + i18n + Webhook Events

**Status:** ✅ Merged via PR #340 (commit `2808d018`) on 2026-05-10
**Branch:** `feat/cli-orchestrator-phase-3-preflight-metadata` (deleted post-merge)
**Goal:** operationalisation layer — make Phase 2's flag flip observable, debuggable, and recoverable

> Plan-agent output (sub-agent `a0386094`) preserved verbatim below, with the actual implementation outcomes folded in at the end.

## §1 — Recon (post-Phase-2 state, line-anchored)

**Already in place after Phase 2:**
- `packages/cli_orchestrator/adapters/base.py:81-105` — `PreflightResult` (frozen dataclass, `succeed()` / `fail(status, reason)`)
- `packages/cli_orchestrator/adapters/base.py:194-244` — `ProviderAdapter` Protocol (sync `preflight`, sync `run`, sync `classify_error`)
- `packages/cli_orchestrator/adapters/temporal_activity.py:81-96` — Phase 2 stub preflight: only `import temporalio.client` check
- `apps/code-worker/cli_orchestrator_adapters/_common.py:32-44` — `binary_on_path(name)` already memoised at module level via `_WHICH_CACHE` dict
- `apps/code-worker/cli_orchestrator_adapters/claude_code.py:67-72` — adapter calls `binary_on_path("claude")` in preflight; identical shape across all 5 worker adapters
- `packages/cli_orchestrator/executor.py:66-92` — Prometheus block already declares 4 metrics (`cli_orchestrator_status_total`, `_duration_ms`, `_fallback_depth`, `_attempt_count`). `_emit_metrics` (95-129) is best-effort, swallows backend failures
- `apps/api/app/services/cli_orchestrator_shadow.py:47-77` — `read_flags(db, tenant_id) -> tuple[bool, bool]` returns `(use_resilient, real_dispatch)`. Hardened with `isinstance` defence
- `apps/api/app/services/webhook_connectors.py:204-227` — `fire_outbound_event(db, tenant_id, event_type, payload)` already wildcard-matches `events: ["execution.*"]` per `_matches_event:191-201`
- `apps/api/app/api/v1/rl.py:65-80` — `POST /rl/internal/experience` already accepts `decision_point` + `state` + `action` (JSONB)
- `apps/api/app/services/rl_experience_service.py:12-21` — `DECISION_POINTS` whitelist **does not** include `"chat_response"` today. `code_task` is present
- `apps/api/app/services/external_agent_reliability.py:78-91` — `_get_redis()` lazy singleton with `redis.from_url(settings.REDIS_URL)`. Reusable shape
- `apps/api/app/services/agent_router.py:1135-1234` — `_resilient_chain_walk` builds adapters dict + `ExecutionRequest`, calls `executor.execute(req)`. **This is the call site to inject the webhook emitter and ExecutionMetadata mirror**
- `apps/web/src/components/RoutingFooter.js:20-145` — currently does NOT call `i18n.t(...)` on `actionable_hint`. Today the hint isn't even read; the component reads `summary.fallback_explanation`. Phase 3 must wire `t(actionable_hint)` consumption
- `apps/web/src/i18n/i18n.js:5-20` — i18n config imports per-namespace JSON files; namespace pattern is `chat`, `common`, etc. No `cli` or `cliErrors` namespace today

**Not present (Phase 3 must add):**
- No `/metrics` Prometheus endpoint exists in `apps/api/app/main.py`. `prometheus_client` is not in api requirements
- No `helm/values/*-alerts.yaml` and no `monitoring/dashboards/` directory
- No `webhook_events.py` wiring file
- No worker-side credential / trust-file / API-enabled checks

## §2 — Decisions

### 2.1 Preflight implementation locations

**Shared helpers** in a new module `packages/cli_orchestrator/preflight.py`. Pure-function helpers; no Redis import at module load (lazy via callable injection).

```python
def check_binary_on_path(name: str) -> PreflightResult: ...
def check_workspace_trust_file(path: str) -> PreflightResult: ...
def check_credentials_present(*, fetch, tenant_id, platform) -> PreflightResult: ...
def check_cloud_api_enabled(*, redis_get, redis_setex, probe, tenant_id, platform, ttl_seconds=300) -> PreflightResult: ...
def check_temporal_queue_reachable(*, redis_get, redis_setex, queue_name="agentprovision-code", ttl_seconds=30, heartbeat_probe) -> PreflightResult: ...
```

Why callable-injection: keeps `cli_orchestrator` package free of `redis` / `temporalio` / vault imports at module load. The api-side wires the real Redis client; tests inject in-memory dicts.

**Per-adapter preflight composition table:**

| Adapter | Checks composed |
|---|---|
| `claude_code` | binary, credentials |
| `codex` | binary, credentials, workspace_trust (`~/.codex/config.toml`) |
| `gemini_cli` | binary, credentials, cloud_api_enabled (`generativelanguage.googleapis.com`) |
| `copilot_cli` | binary, credentials, cloud_api_enabled (org-enabled probe) |
| `opencode` | binary |
| `shell` | binary |
| `temporal_activity` | temporal SDK importable, queue_reachable |

### 2.2 Queue-reachability — heartbeat-staleness, NOT `describe_task_queue`

**Self-review issue resolved.** The naive design table says `describe_task_queue` cached 30s, < 10ms. Reality: TCP/gRPC handshake on cold cache is far above 10ms. **Decision:** infer reachability from worker heartbeat freshness in Redis. Probe = `redis.get("worker:heartbeat:agentprovision-code")` and check timestamp recency. Cost: 1 Redis GET, sub-millisecond. `describe_task_queue` is the cold-cache fallback only.

### 2.3 Preflight latency budget — realistic numbers

| Check | Cold | Warm |
|---|---|---|
| `shutil.which` (memoised) | ~50µs first call, then dict hit | < 1µs |
| Credentials in vault (Postgres SELECT) | 1-5ms in-cluster | N/A — never cached, security boundary |
| Workspace trust file (stat) | < 1ms | < 1ms |
| Cloud API enabled (Redis GET) | < 1ms cached / 5-50ms uncached | < 1ms |
| Queue reachable (Redis GET, heartbeat-staleness) | < 1ms | < 1ms |

**Total realistic budget:** ~10ms cold, < 5ms warm. Phase 3 ship gate uses warm-state p95 < 60ms across rolling 1h window.

### 2.4 ExecutionMetadata location

`packages/cli_orchestrator/metadata.py` — new module. Methods: `from_execution_result(...)`, `to_rl_experience_state()`, `to_rl_experience_action()`, `to_webhook_payload(event_type)` (truncates stdout/stderr to 512B for non-`failed` events).

### 2.5 RLExperience mirror

- Add `"chat_response"` to `DECISION_POINTS` whitelist (single-line edit, no migration). Existing `code_task` consumers unaffected.
- Mirror happens in `executor.py` via NEW callable `mirror_to_rl: Optional[Callable[[ExecutionMetadata], None]] = None` injected on `ResilientExecutor` constructor — keeps the executor unit-testable and free of `apps/api` imports.
- **No new migration.** `RLExperience.state` and `.action` are JSONB.

### 2.6 Prometheus exposition endpoint

The 4 metrics already exist in `executor.py`. They emit but **nothing scrapes them** because there's no `/metrics` endpoint.

**Decision:** add `apps/api/app/api/v1/metrics.py` exposing `prometheus_client.generate_latest()` with the default registry, mounted on `/api/v1/metrics`. Add `prometheus_client` to api requirements. Add the new `cli_orchestrator_preflight_duration_ms` histogram.

### 2.7 Alerts + Dashboard

- `monitoring/alerts/cli-orchestrator.yaml` — PrometheusRule CRD with 4 alerts from design §4.1
- `monitoring/dashboards/cli-orchestrator.json` — Grafana dashboard JSON
- `helm/values/agentprovision-api.yaml` — `serviceMonitor` snippet pointing at `/api/v1/metrics`

### 2.8 i18n key surface — fallback chain to bound the scale

60 strings × 2 locales = 120 entries was the naive read. **Decision:** RoutingFooter resolves through fallback chain:

```
i18n.t(actionable_hint, { defaultValue: i18n.t(genericKey, { defaultValue: englishLiteral }) })
```

Ship 7 generic per-status keys × 2 locales = **14 strings** + 3 per-platform overrides en-only = **17 strings**. Future statuses/platforms add lines without scaffold churn.

### 2.9 Webhook event emission — wire site + db injection

**Self-review issue resolved (webhook payload size):** truncate stdout/stderr to 512B for non-`failed` events. `execution.failed` keeps full 4KB so operators can debug.

**Wire site:** `ResilientExecutor` accepts optional `webhook_emitter: Callable[[str, dict], None]` constructor arg. The api-side `_resilient_chain_walk` builds the closure: `lambda event, payload: fire_outbound_event(db, tenant_id, event, payload)`.

**Six events fired:**
1. `execution.started` — at top of execute() after recursion gate passes
2. `execution.attempt_failed` — per-platform non-success result
3. `execution.fallback_triggered` — when decide() returns action="fallback"
4. `execution.succeeded` — `_finalise_success`
5. `execution.failed` — `_finalise_stop` AND empty-chain terminal exit
6. `execution.heartbeat_missed` — emitted from worker-side `cli_session_manager` on heartbeat staleness (out of executor's path; lands as a separate commit)

## §3 — Implementation order — 9 commits

1. **Preflight shared helpers** — `packages/cli_orchestrator/preflight.py` (5 helpers) + tests + `cli_orchestrator_preflight_duration_ms` histogram
2. **Per-adapter preflight composition** — extend `_common.py` + each adapter's `preflight()` per §2.1 table; 7-platform contract test extended
3. **ExecutionMetadata + RL mirror plumbing** — `metadata.py` dataclass + executor extension + `chat_response` decision point
4. **Prometheus `/metrics` endpoint + dashboards + alerts** — auth via `_verify_internal_key`
5. **Webhook event emission** — `webhook_events.py` + 6 emit sites in executor
6. **i18n keys + RoutingFooter consumption** — 17-string surface with fallback chain
7. **Wire mirror + emitter into `_resilient_chain_walk`** — closures over `db` + `tenant_id`
8. **Heartbeat-missed event** — new internal endpoint `POST /api/v1/internal/orchestrator/events`, worker emit shim
9. **Phase 3 ship-gate doc + cutover playbook update**

## §4 — Self-Review Verdict (Plan-agent's 7-issue resolution table)

| # | Issue | Resolution |
|---|---|---|
| 1 | Preflight latency budget realism | Naive design table said "<5ms creds vault" but in-cluster Postgres p95 is 10-20ms. Cold-cache p95 documented as <80ms; ship-gate alert on rolling 1h p95 dilutes cold starts |
| 2 | `describe_task_queue` cost | Heartbeat-staleness via Redis GET (sub-ms) instead. `describe_task_queue` is cold-cache fallback only |
| 3 | i18n key surface scaling | 60 strings × 2 locales reduced to 17 via fallback chain |
| 4 | RL mirror semantic risk | NEW `decision_point="chat_response"` isolates from `code_task` consumers; single-line whitelist edit, no migration |
| 5 | Webhook payload size | Truncate to 512B for non-`failed` events; full 4KB only on `execution.failed` |
| 6 | `_emit_metrics` already emits but no `/metrics` endpoint exists | Commit 4 mounts `/api/v1/metrics` |
| 7 | Webhook db Session injection in worker context | Worker doesn't have a SQLAlchemy Session — route via new internal endpoint `POST /api/v1/internal/orchestrator/events` (matching existing `/rl/internal/experience` pattern) |

## §5 — What actually shipped (independent-review fixup)

The Plan-agent's self-review caught 7 issues. The implementation agent self-reviewed against its own structured 10-point criteria and gave "all PASS." The **independent reviewer caught 3 Critical blockers** the structured self-review couldn't see by definition:

### C1 — Cloud-API probes were dead code

`_gemini_api_probe` / `_copilot_org_enabled_probe` made unauthenticated GETs to `googleapis.com` / `api.github.com`. Always returned 200/401 from any cluster with internet. `API_DISABLED` would NEVER fire in production.

**Fix:** DROPPED the cloud-API preflight step from gemini_cli + copilot_cli adapters. Deleted 2 tautological tests that only exercised the cached short-circuit path. Updated design doc §6 to mark API_DISABLED preflight as **DEFERRED to Phase 4+** (re-introduce with tenant-keyed probe — `?key=<tenant-api-key>` for Gemini → 403 + `SERVICE_DISABLED` reason; org-scoped token for Copilot). The `Status.API_DISABLED` enum value remains usable from runtime stderr classifier matches.

### C2 — Prometheus label cardinality landmine

`tenant_id` was a label on all 4 metric `Counter`/`Histogram` declarations. With 100+ tenants × 10 statuses × 6 platforms × 3 decision_points = ~18k unique series per metric (Histograms ~12x worse via bucket multiplication → ~216k series). Best-practice cap: ~10k series/metric. Looks fine at 10 tenants, explodes at scale.

**Fix:** REMOVED `tenant_id` from all 4 metric label sets. Per-tenant slicing moves to (a) RLExperience JSONB rows, (b) structured-log extras in `_emit_metrics` `logger.info(extra={"tenant_id": ...})`, (c) ChatMessage.metadata. Updated 2 PrometheusRule alerts (NEEDS_AUTH WoW + API_DISABLED) to aggregate by platform.

### C3 — Emit-failure observability was `logger.debug` (filtered out)

RL mirror + webhook emitter try/except swallows used `logger.debug`. Production log shipping (Loki / CloudWatch) ships at INFO+. A regression breaking RL training data accrual or webhook subscriber notifications would have **zero observable signal**.

**Fix:** Promoted `logger.debug` → `logger.warning(... exc_info=True)` at 3 swallow sites. Added `cli_orchestrator_emit_error_total{kind}` Counter for kind ∈ {`rl_mirror`, `webhook_emit`, `metrics`, `shadow`}. Added `_emit_error_count(kind)` helper. Added `CliOrchestratorEmitErrorRateHigh` PrometheusRule alert (page severity, 5-min window, fires on rate > 0).

## Final test count

```
apps/api full -m 'not integration'   918 pass (matches pre-Phase-2 baseline)
apps/code-worker                     296 pass (272 baseline + 24 new)
packages/cli_orchestrator/tests/      52 pass (new directory)
─────────────────────────────────  ────
Total                              1266 pass
```
