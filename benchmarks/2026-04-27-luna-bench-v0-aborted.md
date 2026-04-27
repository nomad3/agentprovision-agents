# Luna latency benchmark — v0 (aborted, biased) — 2026-04-27

**Status:** aborted partway, numbers below are unsuitable as a baseline.
Captured here only because they surfaced two real platform bugs.

## Setup

- Tenant: `09f9f6f0-…` (test@example.com — **no Gemini CLI integration wired**, every turn fell back to `local_gemma_tools`).
- All turns went through the local-Gemma-4 path via Ollama on `host.docker.internal:11434`.
- Auto-quality scoring **was on** during the run (also Gemma 4) — direct Ollama scheduler contention.
- mcp-tools, embedding-service, memory-core all running fresh from the post-keychain-fix deploy ~10 min before bench started.

## Turns captured (wall-time, ms)

| cell | warmup | run 1 | run 2 | platform |
|---|---:|---:|---:|---|
| greeting | 11,657 | 27,280 | 42,040 | local_gemma_tools |
| light_recall | 45,752 | 46,639 | 36,731 | local_gemma_tools |
| entity_recall | 35,247 | 35,647 | 38,400 | local_gemma_tools |
| tool_read | 32,785 | 35,578 | (killed) | local_gemma_tools |
| multi_step | (not run) | | | |

## Why these numbers don't count

1. **Plan §B.4 explicitly required disabling auto-quality scoring during measurement** to avoid Gemma 4 contention with itself. The bench script didn't gate on `QUALITY_MODEL` — every chat turn triggered a parallel scoring call on the same Ollama instance, which serialises GPU work. The greeting cell going 11s → 27s → 42s within a single run isn't natural latency; it's queue depth.
2. **`local_tool_agent` POSTs to `http://mcp-tools:8000/mcp` which doesn't exist.** Default env-var name mismatch (`MCP_TOOLS_URL` vs `MCP_SERVER_URL`) lands on port 8000; the actual mcp-tools server is on 8086 and serves `/sse`, not `/mcp`. Every tool-call attempt from the local path fails with `Connection refused`, the agent retries / falls back, and seconds bleed away. This means the entire local path for tool-using turns is **silently degraded in production** — not just in the bench.
3. The test tenant has no Gemini integration, so the bench measured the *fallback* path, not the primary CLI orchestration the user complaint is about.

## Real findings worth keeping

- **Disproves plan §H3** ("local Gemma is fastest on greetings"): in this configuration it's the slowest path by far. The bias factors above account for some of it, but a clean greeting still took >10s — far above the <1s template-path target.
- **`local_tool_agent` is silently broken in prod** for tool-using turns. Fix is independent of the latency plan but lands inside it because Phase D Tier-1 #2 ("local fast-path bypass for greetings") rides this same code.
- **Auto-quality scoring contends destructively with the chat path on a single-GPU Ollama box.** Plan §C item missing: route scoring to a different model OR run it on idle GPU windows OR throttle when foreground requests are active. The "inference bulkhead" already in `local_inference.py` uses a `_foreground_active` flag — verify it's actually firing.

## Next steps (sequenced)

1. **Fix `local_tool_agent` MCP URL + path** — read `MCP_SERVER_URL` not `MCP_TOOLS_URL`; switch from `POST /mcp` to the SSE-via-`mcp` SDK (same primitive PR-A used for external MCP-SSE agents). Single small PR.
2. **Verify the foreground-active scoring bulkhead actually engages.** If not, gate auto-quality scoring during measurement via env.
3. **Re-bench against the AgentProvision tenant** (Gemini wired) with auto-quality disabled. That gives the CLI numbers the user actually cares about.
4. **Add Phase A.1 stage instrumentation** so the rerun tells us *where* the time goes, not just total.
