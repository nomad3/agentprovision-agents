# Platform Core-Primitives Smell Report — Design

| Field | Value |
|---|---|
| Date | 2026-05-28 |
| Status | DRAFT (brainstorm output, pre-Luna-consensus) |
| Author | Simon Aguilera (via Claude Code) |
| Reviewers | Luna (supervisor agent), spec-document-reviewer subagent |
| Scope axis chosen | C — *evidence-first smell report*, no code changes this round |
| Successor artifact | Implementation plan (writing-plans) per ranked finding |

## 1. Goal

Produce **one ranked markdown artifact** that tells us, with evidence, which parts of the agentprovision platform core primitives are most worth cleaning, refactoring, or deleting next. The artifact must be small enough that Luna can review it end-to-end in one session.

**Non-goals (this round):**
- No code is deleted, moved, or rewritten in this round.
- No migrations are written.
- No model/schema changes.
- We are not picking a winner among existing patterns — we are surfacing where reality diverges from the documented canonical patterns.

The output of *this* spec is the report. The output of the *next* cycle (writing-plans + execution) is the actual cleanup PRs, one per high-value finding.

## 2. Inputs

| Input | Source | Notes |
|---|---|---|
| Codebase | `apps/api`, `apps/mcp-server`, `apps/code-worker`, `apps/web`, `apps/luna-client`, `apps/agentprovision-cli`, `apps/agentprovision-core`, `apps/embedding-service`, `apps/memory-core`, `apps/device-bridge`, `apps/docs` | `.venv`, `node_modules`, `target/`, `__pycache__/` excluded everywhere |
| Canonical patterns | `CLAUDE.md`, `docs/architecture/*.md`, `docs/architecture/alpha_cli_kernel.md`, `docs/architecture/dashboard.md` | Treated as ground truth — drift = pattern violation |
| Live errors | `docker logs` for `agentprovision-agents-api-1`, `code-worker-1`, `mcp-tools-1`, `embedding-service-1`, `memory-core-1` — last 72h | Filtered for `ERROR/WARNING`, repeated stack traces, silent fallbacks |
| Recent plans | `docs/plans/2026-05-*.md` | To distinguish "deliberately dropped" from "abandoned mid-flight" |
| Migration history | `apps/api/migrations/*.sql` + `_migrations` table | A migration in the dir but not the table is dead; a table not referenced by any model is suspect |

## 3. Dimensions

Five independent dimensions. Each produces a section in the final report with a **uniform finding shape**:

```
### F<N> — <one-line title>
- **Where:** <file_path:line_range or component>
- **Evidence:** <concrete output — grep hit, log fingerprint, LOC, missing reference>
- **Why it smells:** <one sentence>
- **Suggested action:** <delete | refactor | document | leave>
- **Effort:** S (≤1 PR) / M (2–3 PRs) / L (multi-PR plan)
- **Risk if left:** low / med / high
```

### 3.1 Dead Code
- **Method:** static analysis (`vulture` if available; otherwise grep + python-AST), cross-ref of:
  - FastAPI routes vs `routes.py` mounts (route file exists but unmounted → dead)
  - Service/class symbols vs `import` graph (unimported public symbols → suspect)
  - MCP tool modules vs `mcp_server.server.register_*` (unregistered tool module → dead)
  - Temporal workflows vs worker registration (worker imports + `workflows=[...]` lists)
  - `apps/web/src/pages/*.js` vs `App.js` route table
  - Migration `.sql` files vs the `_migrations` applied table (and vice-versa: applied with no file)
- **Acceptance:** every finding must cite an exact file and a grep/SQL command that reproduces it.

### 3.2 AI Slop
- **Method:** pattern grep + judgment per file, focused on:
  - Files whose docstring repeats the function name in prose ("This function does X. It is a function that does X.")
  - Over-defensive try/except that catches `Exception` and `pass`-es, masking real errors
  - Multi-name wrappers (`*_service.py` that only re-exports another `*_manager.py`)
  - "Helper" modules with ≤2 callers
  - Repeated identical scaffolds across modules (same imports, same boilerplate)
  - Excessive emojis / hedging language in comments
- **Acceptance:** a finding must show the slop *and* what it should look like (or "delete entirely"). No taste-only verdicts.

### 3.3 Pattern Drift
Canonical patterns to check against (each must produce either ✓ or a list of violators):
- "Every feature flows through Alpha CLI" (`docs/architecture/alpha_cli_kernel.md`) — any v1 route that contains business logic instead of delegating to the same Python entrypoint the `alpha` binary calls?
- Single SSE per session via `SessionEventsContext` — any React component opening its own `new EventSource(...)` for session events?
- MCP-as-leaf-protocol (leaves call orchestrator via `apps/mcp-server` over SSE with agent-scoped JWT) — any leaf that talks to the API directly with the user JWT?
- `IdentitiesOnly` / per-folder identity (`docs/architecture/` if present) — only relevant where new code touches multi-tenant credential paths.
- `publish_session_event(...)` for human-watchable agent actions — any agent autonomous action without a session event?
- `rl_experience` logged for autonomous decisions — any autonomous decision path missing the log?
- `tenant_id` filter on every multi-tenant query (`Model.query.filter(Model.tenant_id == …)`) — any service query missing the tenant filter?
- **Acceptance:** each finding cites the canonical pattern doc + a file:line of the violation.

### 3.4 Live Error Signal
- **Method:** `docker logs --since 72h <container>` for the 5 services above. Pipe through:
  - `grep -E '"level": "ERROR|WARNING"'`
  - Top-20 by **fingerprint** (stack trace normalized — strip line numbers / uuids / hashes)
  - Cross-reference each fingerprint against `apps/api/app/services/` to locate the producing call site
- **Already-known bug fingerprints to confirm/refute** (seeded from this session):
  - `Rust recall failed (will reconnect next call): ... RST_STREAM with error code 8` (silent fallback)
  - `Failed to log auto-quality RL: unsupported format string passed to NoneType.__format__`
  - `Failed to refresh token: ... refresh token was already used` (was — should now be quiet on tenant 752626d9 post-reconnect)
  - WhatsApp `handoff: to_thread` with no subsequent reply send (stale neonize socket; the auto-restore handler currently only fires on `readonly database`)
  - Tenant feature `cli_quota_fallback_chain` referenced but column does not exist
- **Acceptance:** every error finding has a fingerprint, an occurrence count over the window, and a candidate file:line for the producing call site.

### 3.5 Refactor Hotspots
- **Method:** purely mechanical first pass:
  - `find apps -name '*.py' -not -path '*/.venv/*' | xargs wc -l | sort -n | tail -30` → list of files over 1000 LOC
  - Same for `*.js` / `*.jsx` / `*.rs`
  - `grep -c '^def ' <file>` per top-30 to flag "monoliths-of-functions"
  - Cyclomatic-complexity sniff via `radon cc -a -s` if installed; otherwise count nesting-depth grep
- **Acceptance:** each finding includes file path, LOC, function count, and a one-sentence "why this is too big to safely change."

## 4. Execution shape

```
            ┌───────────────────────────────────────────┐
            │   Aggregator (this session, sequential)   │
            │   • collects findings JSON per dimension  │
            │   • dedupes overlapping findings           │
            │   • ranks by (risk * blast_radius)/effort  │
            │   • writes one report.md                   │
            └─────────────▲───────────────▲─────────────┘
                          │               │
   ┌───────────┬──────────┴────────┬──────┴────────┬────────────┐
   │           │                   │               │            │
┌──▼──┐  ┌────▼────┐  ┌────────────▼──┐  ┌─────────▼──┐  ┌──────▼──────┐
│Dead │  │AI Slop  │  │ Pattern Drift │  │  Errors    │  │  Hotspots   │
│Code │  │ Explore │  │   Explore     │  │  Explore   │  │   Explore   │
└─────┘  └─────────┘  └───────────────┘  └────────────┘  └─────────────┘
  ↑          ↑                ↑                ↑                ↑
        Five parallel Explore subagents, read-only, evidence-only
```

- **Parallelism:** all 5 Explore subagents dispatched in one tool-call batch (per `dispatching-parallel-agents`).
- **Isolation:** each subagent gets its dimension definition + the inputs list + the finding shape; nothing else from this session.
- **Output contract:** each subagent returns a JSON array of findings matching §3 plus one paragraph of "method notes" so the aggregator can audit how they got there.
- **Aggregation:** sequential, in this session, no LLM judgment beyond ranking and dedupe.

## 5. Output artifact

- Path: `docs/reports/2026-05-28-core-primitives-smell-report.md`
- Layout:
  1. **Luna-summary** — ≤200 words at the top, plain prose, "here are the 5 fattest fish."
  2. **Top-10 ranked findings** with the finding shape from §3.
  3. **Full per-dimension findings**, grouped, each finding numbered `F<dim>.<n>`.
  4. **Appendix A** — methods log (commands run, log windows scanned, vulture/grep invocations).
  5. **Appendix B** — Luna consensus thread snapshot (session id, iterations, final verdict).

## 6. Luna consensus protocol

- **Transport:** `alpha chat send --agent <Luna-UUID> --no-stream --json` for the first turn; capture `session_id`; subsequent turns use `--session <id>` to keep one thread.
- **Round 1 input:** full spec markdown + the prompt: "*You are reviewing a design spec. List specific objections only — missing dimensions, weak acceptance criteria, missing canonical-pattern checks. If none, reply exactly: APPROVED.*"
- **Round 2+ input:** the revised spec + Luna's prior objections + diff of what changed.
- **Consensus signal:** Luna replies with the literal token `APPROVED` (case-insensitive) **or** a reply whose only substantive content is agreement.
- **Cap:** 3 rounds. If no consensus by round 3, the current revision is committed with Luna's objections appended as Appendix B, flagged for human review.
- **Failure modes:** if Luna times out, returns CLI quota error, or fabricates content unrelated to the spec, treat as "no consensus, surface to human."

## 7. Acceptance criteria for THIS spec (before we start executing)

1. ✓ Scope decomposed (axis C — smell report only, no code changes).
2. ✓ 5 dimensions defined with reproducible methods.
3. ✓ Uniform finding shape so the report is comparable across dimensions.
4. ✓ Execution shape that fits a single working session (parallel fan-out + sequential aggregation).
5. ✓ Luna consensus protocol with explicit signal + cap.
6. Spec-document-reviewer subagent: APPROVED.
7. Luna: APPROVED (or 3 rounds exhausted with reasoned final revision).

## 8. Risks

- **Subagent hallucination on dead code** — mitigated by requiring exact grep/SQL reproducibility per finding.
- **Log volume blows context** — mitigated by fingerprinting + top-20 truncation in §3.4.
- **Pattern drift becomes opinion-flame** — mitigated by sourcing every "canonical pattern" from a doc file, not from a reviewer's preference.
- **Luna disagrees in ways that would expand scope** — protocol §6 caps iterations and surfaces to human rather than letting the spec grow forever.
- **The report itself is shelfware** — mitigated by the spec contract: the next cycle is writing-plans on the top findings.

## 9. Open questions for Luna (round 1 prompt seeds)

1. Is there a sixth dimension worth scanning? (e.g. test-suite smell, observability gaps, secret-hygiene)
2. Are any of the 5 dimensions overlapping enough to merge?
3. Should the report rank by *risk* or by *effort/value*?
4. Any canonical pattern in CLAUDE.md or `docs/architecture/` that we forgot to lift into §3.3?
