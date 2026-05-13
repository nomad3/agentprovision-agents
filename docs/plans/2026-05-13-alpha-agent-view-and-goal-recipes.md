# `alpha` competitive parity — Agent View + Goal recipes

**Date:** 2026-05-13
**Author:** Claude (opus) at user request
**Status:** Design — awaiting review
**Branch:** `feat/alpha-agent-view-design`

## TL;DR

Two competitor patterns landed publicly on 2026-05-13:

1. **Claude Code "Agent View"** — a multi-session dashboard grouping local
   tasks into **needs input / working / completed** with a peek-and-attach
   interaction (left-arrow to drop into a live task, right-arrow to return).
2. **`/goal` structured prompt template** — a packaged prompt that asks the
   user for *success criteria, operating rules, quality bar, deliverable*
   before any autonomous work starts.

The first overlaps with `alpha`'s existing background-task surface but ships
a UX `alpha` lacks. The second is a *concept* that `alpha` already has the
infrastructure for (Recipes) but no seeded template.

This doc scopes the two follow-ups so they ship as **PR-A** (Goal recipe,
small) and **PR-B** (Agent View / `alpha tasks` dashboard, larger), chained
off this design branch.

## Why parity matters

The eight-differentiator roadmap (`2026-05-13-ap-cli-differentiation-roadmap.md`)
positioned `alpha` as the *orchestrator* of leaf CLIs, not a replacement. The
new Anthropic surface validates that framing — they're acknowledging that
single-process foreground sessions don't scale. But it also raises the bar
on what a terminal-native agent dashboard should feel like.

Where `alpha` already wins:

- Tasks survive terminal close, laptop sleep, machine reboot — theirs don't.
- Tasks are visible from any machine on the same tenant — theirs are local.
- Tasks route through RL, memory, and Temporal — theirs are single-shot.

What's missing is the **at-a-glance, peek-and-attach UX** that makes those
durable tasks feel as approachable as their ephemeral ones.

## Out of scope (deliberately deferred)

- Web-app counterpart to `alpha tasks`. The dashboard already exists at
  `/dashboard` — this design is terminal-only.
- Voice / push-notification triggers. Already on the roadmap as #157.
- Mobile preview app. Tracked separately as the iOS blocker.
- Sandbox-execution previews. Out of scope — `alpha run` already executes
  via the Temporal worker.

---

## PR-A — `goal` recipe + `alpha goal` shortcut

### User story

> "I want to launch a serious autonomous task. Help me phrase it so the agent
>  doesn't drift, knows when it's done, and respects my quality bar."

### Surface

```bash
# Long form — interactive prompt fills in the slots
$ alpha goal
? What outcome do you want? › Migrate the auth module from Auth0 to Clerk
? Success criteria? (one per line; blank to end)
  › All existing tests pass on `pnpm test`
  › Sessions persist across redeploy (smoke-tested manually after rollout)
  › No Auth0 references left in the repo
? Operating rules?
  › Do not modify CI/CD until success criteria met
  › Open a draft PR per logical chunk
? Quality bar? › ship-ready (no //TODO, no `any` in TS, tests green)
? Final deliverable? › PR against main with the migration

→ launching Temporal workflow id=goal-7f3a2c... (alpha watch goal-7f3a2c to follow)

# Short form — pass the goal inline, accept recipe defaults
$ alpha goal "Migrate auth from Auth0 to Clerk" --deliverable "PR against main"

# Equivalent (advanced users)
$ alpha run --recipe goal --prompt "..."
```

### Backend changes

- **`apps/api/app/services/workflow_templates.py`**: add one entry to
  `NATIVE_TEMPLATES` with `name="Goal"`, `tier="native"`, `public=True`,
  `tags=["goal","autonomous","structured"]`. The `definition.steps` is a
  single `type: "agent"` step whose prompt embeds a Markdown contract:

  ```
  ## Goal
  {{input.outcome}}

  ## Success criteria
  {{input.success_criteria}}

  ## Operating rules
  {{input.operating_rules}}

  ## Quality bar
  {{input.quality_bar}}

  ## Final deliverable
  {{input.deliverable}}

  You must satisfy every success criterion before declaring done. Follow
  the operating rules without exception. If a criterion becomes impossible,
  STOP and emit a `needs_input` event with the reason.
  ```

- **No schema migration.** The goal recipe rides existing
  `workflow_templates` table.

### CLI changes

- New `apps/agentprovision-cli/src/commands/goal.rs` — interactive form with
  `inquire` crate (already a dep), or non-interactive when `prompt` flag is
  passed. Wraps `POST /api/v1/recipes/goal/run` (same endpoint `alpha run`
  uses today via `recipe_slug`).
- Register in `apps/agentprovision-cli/src/commands/mod.rs`.
- Tests: parsing flags, success-criteria multi-line collection, fallback to
  `alpha run --recipe goal` body shape.

### Acceptance criteria

1. `alpha recipes ls` shows `goal` in the native section.
2. `alpha goal "foo"` returns a workflow_run_id within 2s on prod tenant.
3. `alpha watch <id>` streams JSONL events from the goal run.
4. The system prompt rendered by the workflow includes all 5 slot values
   verbatim. (Asserted in a Python unit test.)

### Effort: 1 day (CLI ~4h, recipe seed ~2h, tests ~2h)

---

## PR-B — `alpha tasks` dashboard + peek-and-attach

### User story

> "Show me everything running across my machines. Let me jump into the one
>  that needs input. Send me back without killing it."

### Surface

```bash
# At-a-glance, all machines on this tenant
$ alpha tasks
NEEDS INPUT (2)
  goal-7f3a2c  Migrate auth from Auth0 to Clerk          mac-pro · 3m ago
  run-9b1d4f   Bump pg from 15 to 17                     ci-runner-1 · 12m ago

WORKING (5)
  fanout-bb78  Code review: PR #451 (5 providers)        mac-pro · 1m ago
  goal-c4521e  Backfill embeddings for tenant aremko     ci-runner-1 · 4m ago
  ...

COMPLETED (last 10)
  goal-3a91xx  ✓ Sweep stale container refs             saved 1.4k tokens · 18m ago
  ...

# Peek into one — streams the JSONL transcript until you hit `q`
$ alpha tasks attach goal-7f3a2c
[2026-05-13T20:14:02Z] event=tool_call tool=read_file ...
[2026-05-13T20:14:04Z] event=needs_input prompt="Confirm: drop Auth0 tenant key?"
> yes proceed                       # typed inline, sent as the input.reply
[2026-05-13T20:14:09Z] event=resumed ...
^Q                                  # detach without cancelling

# Equivalent to current `alpha cancel`
$ alpha tasks cancel goal-7f3a2c
```

### Backend changes

- **New endpoint** `GET /api/v1/tasks` — returns the union of active
  sessions + workflow runs scoped to the tenant + the requesting user.
  Filters: `?status=needs_input|working|completed`, `?machine=hostname`,
  `?limit=50`.
  - Joins `chat_sessions`, `workflow_runs`, and the most recent
    `ChatMessage` per session.
  - Determines `status`:
    - `needs_input` ⇐ last event was `needs_input` and no reply yet
    - `working` ⇐ workflow status `RUNNING` AND last event < 5 min
    - `completed` ⇐ workflow status `COMPLETED`/`CANCELED`/`FAILED`
- **New endpoint** `POST /api/v1/tasks/{id}/reply` — feeds a reply to a
  `needs_input` task. Body `{ "reply": "..." }`. Validates the task is
  in `needs_input` state, persists as `ChatMessage(role=user)`, signals
  the workflow.
- **No new tables.** All data already lives in `chat_sessions` +
  `workflow_runs` + `chat_messages`.

### CLI changes

- New `apps/agentprovision-cli/src/commands/tasks.rs`:
  - `tasks list` (default) — calls `/api/v1/tasks`, renders the 3-group
    table with `comfy-table` (already a dep via `alpha sessions`).
  - `tasks attach <id>` — opens the SSE stream from
    `/api/v1/tasks/{id}/events` (the same endpoint `alpha watch` already
    uses), buffers lines, and listens on stdin for replies. `q` or `Ctrl-D`
    detaches; `Ctrl-C` is a hard cancel of the local view, NOT the task.
  - `tasks cancel <id>` — shells out to existing `alpha cancel` logic.
- Register `tasks` in `apps/agentprovision-cli/src/commands/mod.rs`.
- Reuse existing `auth::client()` for JWT-scoped HTTP calls.
- Tests: response parsing for each status group, attach-loop happy path
  with a mocked SSE stream, reply submission, detach without cancelling.

### Acceptance criteria

1. `alpha tasks` returns within 1s on a tenant with 50+ tasks.
2. `alpha tasks attach <id>` shows live events with < 500ms tail latency.
3. Typing a line during a `needs_input` event submits it and the task
   resumes (asserted with an integration test that round-trips through the
   Temporal worker).
4. `q` detaches; verified the workflow stays `RUNNING` post-detach.
5. The list excludes tasks from other tenants (RLS-asserted unit test).

### Effort: ~2 days (backend ~6h, CLI ~6h, tests ~4h)

---

## Rollout plan

```
main
 └─ feat/alpha-agent-view-design        ← this doc (PR #N)
     └─ feat/alpha-goal-recipe          ← PR-A: goal recipe (PR #N+1)
         └─ feat/alpha-tasks-dashboard  ← PR-B: tasks dashboard (PR #N+2)
```

Per `feedback_chain_pr_branches`, each branch is cut off its predecessor —
not main — because both PR-A and PR-B will touch `commands/mod.rs` and would
otherwise collide on merge.

Each PR ships behind the existing `alpha` binary; no flag-gating needed
because the new commands are additive. The `goal` recipe lands as
`tier="native"` so it's available to every tenant on next API restart.

## Risk register

| Risk | Mitigation |
|---|---|
| `alpha tasks` list query is slow for tenants with >1000 sessions | Hard `LIMIT 50` server-side, paginate with `?before_id=` cursor |
| Attach stream leaks file descriptors on dropped connection | Use existing `tokio::select!` shutdown pattern from `watch.rs` |
| Reply endpoint is abused to inject malicious instructions | Reply goes through the normal `ChatMessage` content sanitiser; same surface `/chat` already exposes |
| Goal recipe drifts from operating rules (LLM ignores them) | Out of scope for v1 — meta-adjudicator follow-up (#187) handles compliance scoring |

## What we are NOT building

- **Multi-machine RPC.** Each `alpha tasks attach` call goes through the
  central API; we do not open peer-to-peer streams between user machines.
- **Local-only mode.** `alpha tasks` requires a logged-in JWT — it is a
  tenant-scoped view, not a `ps` for local processes.
- **`/bg` analog.** Already shipped as `alpha run --background`.

---

## Amendment 2026-05-13 — as-shipped reconciliation

The design above was the original spec. PRs #453 (PR-A) and #454 (PR-B)
deliberately reduced scope on several items after implementation surfaced
a schema gap. This section lists every divergence so a future reader
reading the doc as historical record isn't misled.

### PR-A — what shipped vs. designed

- **Run endpoint.** Designed: `POST /api/v1/recipes/goal/run`. Shipped:
  `POST /api/v1/dynamic-workflows/{target_id}/run` after a resolve-by-
  name + install-if-missing dance through the existing
  `dynamic-workflows` surface. Same functional outcome.
- **Interactive prompts crate.** Designed: `inquire`. Shipped: `dialoguer`
  (already a workspace dep). No `inquire` import was added.
- **Resolve-by-name vs. UUID.** As-designed.
- **Dedupe via `source_template_id`.** As-designed.

### PR-B — deferred to v2

The original design promised `needs_input` detection + reply UX. The
`workflow_runs` schema has no canonical `awaiting_input` column today,
and every heuristic we considered (last-event-from-agent, idle-since-X)
would mislead users. Deferring the entire feature in v1 is honest; the
schema work is now the gating item.

Deferred to a follow-up PR (depends on schema migration):

- **`needs_input` bucket** in `alpha tasks` output. v1 prints
  `NEEDS INPUT: not yet surfaced. Run alpha watch <id> on a workflow
  you suspect is blocked.` — server tells the CLI the bucket is
  unsupported via a new `supports_needs_input: false` response field.
- **`POST /api/v1/tasks/{id}/reply` endpoint** — depends on
  needs-input detection.
- **Custom `tasks attach` peek-and-reply loop** with `q`-to-detach and
  inline reply input. v1 `alpha tasks attach <id>` simply delegates
  to `alpha watch <id>` via the same SSE source.

### PR-B — endpoint path & data sources changed

- **Path.** Designed: `GET /api/v1/tasks`. Shipped:
  `GET /api/v1/dashboard/tasks` — mounted under `/dashboard` because
  the v1 root already has `/tasks` claimed by `agent_tasks.router`
  (orchestration-internal `AgentTask` records). The two concepts are
  distinct: `agent_tasks` is per-agent invocation state, the dashboard
  rollup is human-facing.
- **Data sources.** Designed: union of `chat_sessions` + `workflow_runs`
  + most-recent `ChatMessage` per session. Shipped: `workflow_runs`
  JOIN `dynamic_workflows` only. `chat_sessions` + `chat_messages` were
  only needed for the deferred `needs_input` heuristic.
- **Filters.** Designed: `?status=...&machine=...&limit=...`. Shipped:
  `?limit=N` only. `machine` (machine-hostname filter) requires a
  `machine_id` column on `workflow_runs` we don't have today; punted.
- **CLI rendering crate.** Designed: `comfy-table` (already a dep).
  Shipped: bare `println!` with manual column padding — `comfy-table`
  wasn't actually in `Cargo.toml`, design doc was wrong.

### Acceptance criteria — adjusted

- **PR-A AC#2** (`<2s on prod tenant`): not measured; the verification
  step ran `seed_native_templates(db) → created: 1` against the live API
  container but didn't time the end-to-end dispatch. Treat as
  aspirational, not asserted.
- **PR-B AC#2/3/4** (attach latency, needs-input reply round-trip,
  `q`-detach semantics): untestable as written — deferred with the
  `needs_input` feature above.
- **PR-B AC#5** (tenant isolation): asserted structurally via
  self-chaining MagicMock in `tests/api/v1/test_dashboard_tasks.py`.
  A real integration-DB test is the proper guardrail — tracked as a
  follow-up risk in the register below.

### Risk register addendum (new entries surfaced during build)

| Risk | Status |
|---|---|
| `workflow_runs` has no `awaiting_input` column — blocks `needs_input` UX | Confirmed during PR-B; schema migration is gating |
| Stale "running" zombies (worker crashed pre-terminal-status) bloat the working bucket | Open — no reaper exists; PR-B punts with the 24h completed-lookback |
| Resolve-by-`(name, tier)` for recipes is ambiguous if a tenant somehow seeds two native rows | Confirmed during PR-A review (#453 I3) |
| Prompt-injection via `{{input.outcome}}` Markdown splicing | Confirmed during PR-A review (#453 I4) — recipe-level mitigation deferred to a sibling sanitisation PR |

### What did NOT change

- The chain rollout (`main → design → goal → tasks`) matches the diagram.
- The `tier="native"` seeding model.
- The interactive-vs-non-interactive split on `alpha goal` (with the
  contract drift caught in #453 review and fixed in-PR).
- The "Multi-machine RPC / Local-only mode / `/bg` analog" non-goals.

---

## References

- Eight-differentiator roadmap — `docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`
- Recipes (PR #447) — `workflow_templates.py`, `commands/recipes.rs`
- `alpha watch` SSE contract — `commands/watch.rs`, `api/v1/workflows/{id}/events`
- Background tasks (PR #432, #433) — `--background` flag, durable Temporal
  worker on `agentprovision-code` queue
