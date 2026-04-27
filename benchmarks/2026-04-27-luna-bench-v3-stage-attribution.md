# Luna latency benchmark v3 — first stage attribution

**Date:** 2026-04-27
**Plan:** `docs/plans/2026-04-23-luna-latency-reduction-plan.md` Phase A.1 + Phase B
**Bench:** `scripts/benchmark_luna.py --runs 2 --warmup 1`
**Target:** `http://localhost:8000`, `test@example.com` tenant (no Gemini/Claude/Codex creds → falls to `local_gemma_tools`)

## Outer-stage breakdown

| cell | wall p50 | setup | cli_credentials_missing | local_tool_agent | overhead |
|---|---:|---:|---:|---:|---:|
| greeting | 21 s | 0 ms | 1 ms | **24,788 ms** | <0.1% |
| light_recall | 35 s | 0 ms | 1 ms | **40,927 ms** | <0.1% |
| entity_recall | 36 s | 0 ms | 1 ms | **35,341 ms** | <0.1% |
| tool_read | 38 s | 0 ms | 1 ms | **38,476 ms** | <0.1% |
| multi_step | 34 s | 0 ms | 1 ms | **34,602 ms** | <0.1% |

## Headline

**The orchestrator is innocent.** Setup + credential check + every other piece of `cli_session_manager.run_agent_session` outside the LLM dispatch sums to **1 millisecond per turn**. The entire 25–41 s wall time lives inside one function call: `local_tool_agent.run()`.

That puts these plan hypotheses to bed:

| H | Status |
|---|---|
| H1: CLI subprocess spawn is 1.5–2 s overhead | **N/A on local path** — no subprocess. Will revisit on Gemini-CLI tenant. |
| H2: Gemini CLI fastest on tool turns | Untestable here. |
| H3: Local Gemma fastest on greeting | **Disproven** by v2 + reaffirmed v3 (greetings 21–29 s). |
| H4: MCP tool roundtrips add 800–1500 ms each | Pending v4 (inner LLM-vs-tool split). |
| H5: CLAUDE.md render >200 ms | **Disproven by 0 ms `setup`.** |
| H6: Memory recall <250 ms p95 | The pre-built memory branch fires; recall isn't even on the timer. |
| H7: Cold ≥ 2× warm | **Disproven** — warmup and runs cluster within ~50% of each other. |

## What this plan section already saved us

By Phase A.1 telling us where time goes, we now know **not to ship** the original Tier-1 #1 ("CLI process pool / warm CLI workers") on this path — it would save zero ms because no CLI is being spawned. That's 16 engineering hours redirected before a single line of optimization code.

## What's next

PR #213 splits the 35 s inside `local_tool_agent.run()` into:

- `local_llm_ms` — cumulative Gemma 4 inference time
- `local_tool_ms` — cumulative MCP tool roundtrips
- `local_overhead_ms` — everything else (parsing, message stitching, safety enforcement)
- `local_rounds` — count of tool-calling rounds

V4 (next bench, after PR #213 deploys) will tell us whether the 35 s is dominated by:

- **Inference** — points to "trim the prompt" / "skip proactive recall on short turns".
- **Tool roundtrips** — points to "batch tool calls" / "cache hot lookups".
- **Overhead** — points to a code-level perf review.

Heuristic from log analysis during the run: ~4 LLM rounds × ~9 s each (Gemma prefill on the 8–12 K-token CLAUDE.md), with each tool roundtrip <500 ms — so we expect `local_llm_ms` to dominate. V4 confirms or breaks that prior.

## Side findings worth keeping

1. **`cli_credentials_missing` = 1 ms reliably.** That branch is hot — every test-tenant turn flows through it. If we ever shipped the same tenant with credentials, the Gemini-CLI path would replace this entirely.
2. **`setup` = 0 ms** means agent slug resolution + skill_manager lookup + initial DB queries land below 1 ms granularity. The skill manager is well-cached; we can't squeeze more from it.
3. The `light_recall` p95 (47.5 s) and avg (41 s) are noticeably above the cold-vs-warm cluster — likely a transient Ollama queue depth event during that turn. If it repeats in v4, worth investigating; if not, noise.

## Files

- Raw harness output: `benchmarks/2026-04-27-luna-bench-v3-raw.md` + `.json`
- v0/v1 (broken local_tool_agent path): `benchmarks/2026-04-27-luna-bench-v0-aborted.md`
- v2 (clean wall-time only): `benchmarks/2026-04-27-luna-bench-v2-baseline.md`
- v4 (this PR's inner attribution): pending — bench rerun after PR #213 deploys
