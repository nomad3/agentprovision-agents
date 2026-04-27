# Luna latency benchmark v4 — final attribution

**Date:** 2026-04-27
**Plan:** `docs/plans/2026-04-23-luna-latency-reduction-plan.md`
**Bench:** `scripts/benchmark_luna.py --runs 2 --warmup 1`
**Path measured:** `local_gemma_tools` (test tenant has no Gemini/Claude/Codex creds; falls through to local Ollama Gemma 4)

## TL;DR

| cell | wall p50 | local_llm avg | local_tool avg | local_overhead avg | LLM share |
|---|---:|---:|---:|---:|---:|
| greeting (`hola luna`) | 21.8 s | 25,792 | 62 | 7 | **99.7 %** |
| light_recall | 33.5 s | 37,331 | 86 | 12 | **99.7 %** |
| entity_recall | 36.9 s | 39,173 | 52 | 5 | **99.9 %** |
| tool_read | 34.9 s | 39,704 | 89 | 16 | **99.7 %** |
| multi_step | 33.0 s | 34,212 | 61 | 6 | **99.8 %** |

**All five cells make exactly 2 LLM rounds.** Tool roundtrips: 50–90 ms total per turn. Every other line of code in the chat path: ≤16 ms. Latency is **entirely** Gemma 4 inference cost on this path.

## Plan hypotheses, settled

| H | Status |
|---|---|
| H1 — CLI subprocess spawn 1.5–2 s | **N/A on local path.** |
| H2 — Gemini CLI fastest on tool turns | **Untestable on this tenant.** Need `--token` against AgentProvision. |
| H3 — Local Gemma fastest on greetings | **Disproven.** Greetings are 22–30 s on local; can't be "fastest" without a sub-3 s path. |
| H4 — MCP tool roundtrips 800–1500 ms each | **Disproven by orders of magnitude.** Total per-turn tool time: 50–90 ms. |
| H5 — CLAUDE.md render >200 ms | **Disproven.** `setup` measured 0 ms across all cells. |
| H6 — Memory recall <250 ms p95 | Not directly tested — the `pre_built_memory_context` branch ran on every turn, so recall didn't enter the timer. |
| H7 — Cold ≥ 2× warm | **Disproven.** Warmup and runs cluster within ~50 % of each other. |

## Why every turn is 2 rounds × ~13–20 s

Luna's persona (`apps/api/app/agents/_bundled/luna/skill.md`) instructs:

> AFTER EVERY CONVERSATION MESSAGE from the user:
> 1. Did they mention a person? → create or update entity
> 2. Did they mention a company? → create or update entity
> 3. Did they mention a project, task, or goal? → create entity
> 4. Did they reveal something about themselves? → record_observation on the user's entity

Plus the explicit `recall_memory` directive on every new topic. Gemma 4 obeys: round 1 calls `find_entities`, round 2 calls `search_knowledge`, then a 3rd round (or final summary call) generates the user-visible reply. On this M4 with an 8–12 K-token CLAUDE.md, prefill alone is ~10–15 s per round × 2–3 rounds = 25–45 s per turn.

That's the bench result. Not the orchestrator. Not the CLI. Not the MCP tools. **The persona's "always recall first" rule, multiplied by Gemma's prefill cost, multiplied by a large prompt.**

## Tier-1 actions, re-ranked by measured leverage

The plan's original Tier-1 list rewrites after this data. New estimates against actual greeting wall time of 22 s.

| # | Action | Expected save | Eng hours | Risk | Status |
|---|---|---:|---:|---|---|
| 1 | **Greeting fast-path template** (intent=greeting & ≤30 chars & no `?` → return template, skip LLM entirely) | ~22 s on greetings (≈25 % of aremko WhatsApp volume) | **6** | low | **Implemented + tested** in this session, PR open. |
| 2 | **Trim CLAUDE.md for the local path** (drop episodic recall + world-state + self-model + full tool schemas; keep persona + immediate context) | ~5–8 s per round × 2 rounds = 10–16 s on every cell | **8** | medium | Designed; not implemented yet. |
| 3 | **Skip proactive recall on short turns** (override Luna's "always call find_entities first" for ≤3-word inputs that clear the greeting fast-path but aren't templates) | ~10–15 s per qualifying turn (cuts 2 rounds → 1) | **4** | low | Designed; needs persona update + router gate. |
| 4 | **Pre-warm Gemma model** (after api restart, model reload adds ~50 s to the first turn — see warmup numbers in v4 vs v3) | ~30 s on first turn after deploy | **2** | low | Ollama `keep_alive` parameter; trivial. |

Items 2–4 land if/when 1 is shipped and we re-bench.

## What this kills from the original plan

- **Tier-1 #1 (CLI process pool / warm CLI workers — 16 eng hours):** zero ms saved on this path; no CLI is spawned. **Unfunded.**
- **Tier-2 #4 (reduce CLAUDE.md size — original estimate 400 ms):** under-estimated by ~30×. Becomes Tier-1 #2 above with a 10–16 s estimate.
- **Tier-3 #7 (skip MCP tool init on no-tool turns — 500 ms):** dwarfed by LLM cost; <100 ms per turn total goes to MCP. Unfunded until LLM cost is solved.

## Out of scope of this bench

- **Gemini-CLI tenant.** The original user complaint ("Luna feels slow on WhatsApp") was on aremko, which routes through Gemini CLI. The CLI path's costs (subprocess spawn, MCP SSE handshake, gemini-cli's own prompt processing) are different from Gemma 4 prefill. To bench it: run `scripts/benchmark_luna.py --token <AgentProvision-or-aremko-JWT>`.
- **Multi-tenant load.** Single-tenant numbers; concurrent-tenant degradation is a separate question.
- **Remote vs M4 GPU.** Numbers are specific to this M4 with native Ollama. Cloud-hosted Gemma 4 (e.g. on Groq, Together) would be 5–10× faster prefill and might reshuffle the ranking.

## Files

- `benchmarks/2026-04-27-luna-bench-v4.json` — raw rows.
- `benchmarks/2026-04-27-luna-bench-v4-raw.md` — auto-generated harness output.
- `benchmarks/2026-04-27-luna-bench-v3-stage-attribution.md` — outer-stage attribution (PR #211).
- `benchmarks/2026-04-27-luna-bench-v2-baseline.md` — pre-A.1 wall times only.
- `benchmarks/2026-04-27-luna-bench-v0-aborted.md` — early run that surfaced the local_tool_agent MCP bug.

## Next bench step

After PR #215 (greeting fast-path) deploys: re-bench. Expect greeting p50 to drop from 22 s to <100 ms, all other cells unchanged. That confirms the template path + leaves Tier-1 #2 (CLAUDE.md trim) as the next leverage.
