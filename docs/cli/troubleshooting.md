# `alpha` CLI troubleshooting (v0.7.5)

Known issues, workarounds, and recovery recipes. Last updated 2026-05-18
after the v0.7.5 release.

Issues are grouped by symptom. If you don't see your symptom here, also
check the legacy quick-fixes at the bottom of
[README.md](README.md#troubleshooting).

## Auth & install

### `alpha upgrade lost my auth`

**Symptom:** after `alpha upgrade` from v0.7.4 → v0.7.5, every command
exits with `error: authentication required` and `alpha status` shows
`authenticated: no`.

**Cause:** v0.7.5 restored the OS keychain as the default token store.
v0.7.4's plaintext fallback path is no longer auto-discovered, so the
old token effectively vanished from the CLI's point of view.

**Fix:** just re-authenticate.

```bash
alpha login
alpha status        # should now show your email + tenant
```

The previous token is harmless residue in the old path — nothing else
to clean up.

### `alpha status` says authenticated but every other command 401s

Token TTL is ~30 minutes. `alpha status` only checks that *a* token
exists locally — it doesn't validate against the server. If the token
expired between `alpha status` and your next call, re-run `alpha login`.

## `alpha run` / `alpha watch`

### `alpha run "..."` (no `--fanout`) returns "Phase-1-prototype synthetic response"

**Cause:** the single-provider real-dispatch path is **not** yet wired.
Only `alpha run --fanout <cli>` (PR #573) hits real Temporal today.

**Workaround:**

```bash
# Use --fanout with one CLI instead
alpha run --fanout claude_code "<prompt>" --background
```

Phase 3 extension to wire `--providers` and naked `alpha run` to real
dispatch is queued in
[`docs/plans/2026-05-18-alpha-cli-delegation-pattern.md`](../plans/2026-05-18-alpha-cli-delegation-pattern.md).

### `alpha run --providers a,b,c` returns a synthetic stub

Same root cause as the above — fallback-chain routing is the next item
in the Phase-3 queue. Use `--fanout` for now (note: `--fanout` is
parallel, `--providers` is sequential fallback — semantics differ).

### `alpha watch <id>` crashes with `AttributeError: 'WorkflowExecutionDescription' has no attribute 'workflow_execution_info'`

**Cause:** the server-side orchestration worker is on a Temporal SDK
older than 1.10, where `WorkflowExecutionDescription` had a nested
`.workflow_execution_info` accessor. PR #575 flattened that.

**Fix:** redeploy the orchestration pod against `temporalio>=1.10`.
The CLI is already on the new shape.

### `alpha run --fanout` task stays `queued` forever

Check the `USE_REAL_FANOUT_WORKFLOW` flag — if it's not `true` in
`apps/api/.env` (or the equivalent in your Helm values for K8s), the
backend keeps you on the synthetic stub. Self-hosters need to flip
it explicitly.

## `alpha review`

### Review stays `running`, no findings

**Symptom:** `alpha review start "<ref>" --clis ...` returns a
`review_id`, but `alpha review status <id>` shows `status: running`
indefinitely with no findings recorded.

**Cause:** the fire-and-forget Temporal dispatcher in
`apps/api/app/services/review_dispatch.py::_runner` uses a daemon
thread that calls `asyncio.run` on a fresh event loop. In practice
the `ReviewWorkflow` start call silently never fires. Manual
`Client.start_workflow` works; the threading wrapper doesn't. A
hotfix is queued.

**Workaround — drive the consensus loop manually.** The aggregator,
the `reviews_coalitions` table, and the `/record` endpoint are all
fully live, so you can feed each CLI's output in directly:

```bash
# 1. Start a review (it'll sit in `running` waiting for findings)
REVIEW_ID=$(alpha review start "#570" --clis claude_code,codex,gemini_cli --json | jq -r .review_id)

# 2. Run each CLI yourself (manually or via `alpha run --fanout <cli>`)
#    and capture its review output as raw text.

# 3. POST each CLI's output to /record
curl -X POST "https://agentprovision.com/api/v1/reviews/$REVIEW_ID/record" \
    -H "Authorization: Bearer $(alpha status --json | jq -r .access_token)" \
    -H "Content-Type: application/json" \
    -d '{"cli": "claude_code", "raw_text": "...review output..."}'

# Repeat for codex, gemini_cli. The aggregator runs synchronously when
# the last expected CLI reports, then status flips to awaiting_response.

# 4. Poll
alpha review status $REVIEW_ID
```

The aggregator clusters per-CLI findings by `(file, overlapping line
range, Jaccard ≥ 0.4 on description tokens)`; clusters of size ≥ 2
become `agreed_findings`.

### `alpha review start #570` silently runs with no ref

**Cause:** `#` is a shell comment marker. The CLI never sees the ref.

**Fix:** quote it.

```bash
alpha review start "#570" --clis claude_code,codex,gemini_cli
```

### `alpha review watch <id>` disconnects after ~100s

Cloudflare cuts idle SSE streams around the 100s mark. Just re-run
`alpha review watch <id>` — the underlying `reviews_coalitions` row
is authoritative, you don't lose anything. The async/queue-buffered
migration (PR #570) is the long-term fix.

## `alpha chat send`

### Cloudflare 524 on `alpha chat send`

**Symptom:** long prompts to `alpha chat send` hit a `524` from
Cloudflare and the CLI exits with a partial response.

**Cause:** `alpha chat send` streams over SSE through the Cloudflare
tunnel, which terminates idle streams at the 524 deadline.

**Fix:** use `alpha run --fanout <cli> --background` instead. The
durable Temporal path doesn't depend on a long-held HTTP connection
and survives Cloudflare's idle cutoff.

```bash
alpha run --fanout claude_code "<long prompt>" --background
# Returns immediately with a task_id; tail with:
alpha watch <task_id>
```

The async chat-result pattern (PR #570 — `/messages/start` + `/jobs/{id}/events`
+ `/jobs/{id}/cancel`, backed by `chat_jobs` table from migration 137)
will replace the SSE path for `alpha chat send` itself. CLI-side
feature flag to opt in to the new path is queued.

## `alpha integration`

### `alpha integration ls` fails with a serde error

**Symptom:**

```
error: failed to deserialize integrations list:
  invalid type: map, expected a sequence at line 1 column 1
```

**Cause:** the server-side endpoint changed shape — it returns a
JSON object keyed by integration name, while the CLI's `Vec<Integration>`
deserializer still expects an array. The fix is on the CLI side and
will ship in the next release.

**Workaround:** hit the API directly.

```bash
curl -H "Authorization: Bearer $(alpha status --json | jq -r .access_token)" \
     https://agentprovision.com/api/v1/integrations | jq
```

## Cross-cutting

### `alpha upgrade` succeeds but `alpha --version` still shows the old binary

`PATH` likely has multiple `alpha` binaries. Check:

```bash
which -a alpha
```

The installer drops `alpha` into `~/.local/bin/` — make sure that's
ahead of `/usr/local/bin/alpha` or wherever the older one lives. Or
just delete the stale binary.

### Self-hosters: `--fanout` real dispatch isn't working

Three knobs must be set:

1. `USE_REAL_FANOUT_WORKFLOW=true` in `apps/api/.env` (or Helm).
2. Orchestration worker on `temporalio>=1.10` (PR #575).
3. Orchestration worker passes an explicit `activity_executor`
   (`ThreadPoolExecutor`) when constructing the `Worker` — the
   `record_review_finding`, `load_review_state`, and
   `aggregate_findings` activities are sync and Temporal 1.10
   requires this for sync activities (PR #577).

Helm chart in this repo is already aligned; out-of-tree deployments
need to mirror.
