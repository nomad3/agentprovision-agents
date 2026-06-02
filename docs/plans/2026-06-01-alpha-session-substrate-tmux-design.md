# Alpha Session Substrate — persistent tmux-backed CLI sessions as the network-of-agents execution plane

**Date:** 2026-06-01 · **Status:** Design (brainstormed; converged from a web-research workflow + Luna research; pending Codex + Luna spec review)
**Drivers:** the per-turn spawn-and-die CLI model (`claude_interactive.py`) that produces exit-143 / freeze / onboarding re-seed; no session persistence; no parallel sub-agents; CLI-specific completion hacks.
**Related:** [`docs/architecture/alpha_cli_kernel.md`](../architecture/alpha_cli_kernel.md) · A2A coalitions (`docs/plans/2026-04-12-a2a-collaboration-demo-design.md`) · Claudia bridge (`docs/plans/2026-06-01-claudia-bridge-consensus-plan.md`) · the leaf-agent-inbound-via-MCP pattern.

## Thesis — this is Alpha's session substrate, not a subprocess hack

The "network of agents" was the original vision. This design makes it real at the execution layer:

- **Outbound (Alpha → agent):** the orchestrator drives every CLI agent through one typed `SessionControl` protocol expressed as **Alpha kernel verbs** (`alpha session open|send-turn|read-result|interrupt|close`). Thin v1 HTTP routes delegate to the same Python entrypoint the `alpha` binary calls — no business logic in the route (per the kernel principle).
- **Inbound (agent → Alpha):** an agent reports turn completion / asks for input by **calling an MCP tool** (`submit_result`, `request_input`). That is *literally the network-of-agents inbound path* — leaves calling back into the orchestrator over MCP-over-SSE with an agent-scoped JWT (the existing `leaf_agent_inbound_via_mcp` pattern), not a bespoke side-channel.
- **Substrate:** each agent's CLI runs in a **persistent tmux session** (the PTY container + human viewport), driven via **tmux control mode** — the execution plane. tmux holds no truth; durable state lives in Postgres/Redis + the CLI's own session id.

Alpha is the brain; tmux is the body; MCP is the nervous system. The same protocol works whether the session lives in a cloud `code-worker` pod or on a paired laptop — the agent doesn't care where its tmux session is.

## The problem we're replacing

Today (`apps/code-worker/cli_executors/claude_interactive.py` + `cli_runtime.py`): **every chat turn cold-spawns a fresh `claude`/`codex` PTY** via `subprocess.Popen`, drives it with a brittle screen-scraping state machine (`decide_pty_action`), and **kills it** at turn end. Consequences, all observed this session:
- Cold launch every turn → startup-chrome flood, onboarding re-seed, fragile submit.
- Completion inferred from **wall-clock silence** + an **answer-file** scrape → false kills. A long "pull my work repos" turn went silent past the window → `/exit` → **SIGTERM → exit 143** (the bug we chased all day; the watchdog tweak only delayed it).
- No persistence, no parallelism, per-CLI hacks.

The research (web-grounded + Luna, independently convergent) is blunt: **idle-by-silence is a lie, alt-screen scraping is unreliable, and `SIGTERM`-to-end-a-turn is what produces exit-143.** The fix is structural, not another watchdog tweak.

## Decisions locked in brainstorming

| Decision | Choice | Why |
|---|---|---|
| Substrates | **Both — one protocol** | agent is substrate-blind; pod and laptop are just endpoints |
| First build slice | **Robustness, cloud-first** | fixes today's pain, ships fastest, lowest risk |
| Session identity | **Per conversation** | kills per-turn cold-launch within a conversation; maps to existing `chat_sessions` (already bound to an agent + `session_dir`); clean isolation |
| Scope | **All CLIs** (Claude Code, Codex, Gemini, Copilot, OpenCode) | CLI-agnostic substrate + thin per-CLI adapters |
| Turn engine | **Interactive mode only** | `claude -p` is blocked on subscription auth (confirmed by Simon); interactive is the only path. Persistent sessions are what make interactive viable. |
| Completion signal | **MCP callback** (`submit_result`/`request_input`) | deterministic, CLI-agnostic (all CLIs already call our MCP tools), replaces silence/answer-file/SIGTERM entirely |

## Architecture

```
            Orchestrator (Temporal / Luna)  —  ONE protocol, substrate-blind
                       │  Alpha verbs:  session open · send-turn · read-result · interrupt · close
        v1 thin routes │  (delegate to the same entrypoint the `alpha` binary calls)
        ┌──────────────┴───────────────────┐
   SessionEndpoint(pod-local)         SessionEndpoint(ap-broker on laptop)
   we own it → direct                 outbound-only · deny-by-default · consent + allowlist
        └──────────────┬───────────────────┘
                 TmuxController   (CLI-AGNOSTIC)
        tmux -CC control mode · session-per-conversation · panes/windows = sub-agents
        stable $session/@window/%pane IDs · lifecycle events · attach for a human
                       │
            Turn-engine adapter   (PER-CLI: claude · codex · gemini · copilot · opencode)
        owns: launch the interactive REPL once · inject a turn when IDLE · nothing else
                       │
   inbound ◄───────────┴──────────  agent calls MCP:  submit_result(...) · request_input(...)
   (network-of-agents path, leaf → Alpha over MCP-over-SSE, agent-scoped JWT)
                       │
        Durable state OUTSIDE tmux:  session_substrate rows (Postgres) + Redis liveness
        + CLI session id for in-CLI continuity (tmux-resurrect does NOT preserve agent state)
```

### Layer responsibilities (each independently testable)
1. **Alpha verbs + v1 routes** — the public contract. `alpha session send-turn <session> <message>` → `POST /api/v1/session/{id}/turn`. Thin; delegates.
2. **SessionEndpoint** — resolves where the session lives and how to reach it: `pod` (direct, in the `code-worker`) or `broker` (a paired laptop via the outbound-only `ap-broker`). Same command surface; different transport + policy profile.
3. **TmuxController** — CLI-agnostic. `create_session`, `create_pane`, `send_text`, `send_enter`, `subscribe_events`, `capture` (break-glass), `kill`, `attach_metadata`. Speaks tmux control mode; addresses by stable IDs; applies `pause-after` flow control.
4. **Turn-engine adapter (per CLI)** — the only CLI-specific code. Launches that CLI's interactive REPL inside the session once; injects a turn's text only when the session is IDLE; relies on the MCP callback for completion. Reuses the per-CLI knowledge already in `cli_executors/{claude,codex,gemini,copilot}.py`.
5. **MCP completion tools** — `submit_result(result)` and `request_input(question)` served by `apps/mcp-server`; calling `submit_result` *is* how the agent returns its answer (it cannot silently "forget" without failing to deliver). Crash/exit is caught by the control-mode `%exit` event, not silence.

### The turn loop (interactive, idle-gated, callback-completed)
```
session IDLE
  → send_turn(message)            # delivered ONLY when IDLE — no mid-turn input collision
  → agent PROCESSING              # may call request_input(...) if it needs a decision
  → agent calls submit_result(r)  # turn-done signal + the deliverable, in one MCP call
  → orchestrator records r, session → IDLE   (repeat)
crash/exit → control-mode %exit → surface error + respawn session (durable state intact)
```
No silence timer. No `SIGTERM`-to-end-turn. No `-p`. No answer-file scraping. Temporal heartbeats stay well under the 240s cancel window so a long-but-alive turn is never `CancelledError`'d.

## Security — one protocol, two policy profiles

The wire protocol is identical; the trust posture differs because ownership differs (Warp's local-vs-cloud agent split is the reference).

- **Pod endpoint (we own it):** direct; standard tenant isolation; the session runs in our `code-worker`.
- **Broker endpoint (the user's laptop):** a cloud service that can drive a real terminal is, by construction, remote arbitrary-command execution with the user's full identity (SSH keys, cloud CLIs, git). So:
  - **`ap-broker`** daemon the user runs as themselves; **outbound-only** long-lived TLS to the Alpha relay (no inbound listener, no firewall changes — VS Code Tunnels / Tailscale / ngrok shape). The cloud never reaches *in*.
  - The broker is the **sole enforcement boundary**: it accepts **only typed `SessionControl` commands**, never raw shell from the cloud. Per-repo/workspace **explicit consent**; allow-listed roots, env vars, commands; **deny-by-default**; sessions are **visible** and **locally revocable/killable**.

## Parallelism = the network of agents

- **Session-per-sub-agent** (CAO/Claude-Squad pattern): each sub-agent its own tmux session/pane, own PTY, own lifecycle; a human can `tmux attach` to steer exactly one; crashes are blast-radius-contained.
- **Fan-out / collect via the MCP inbox** (CAO primitives): `assign` (spawn async + callback), `submit_result`/`send_message` (delivered **only when the target is IDLE** — the structural fix for input collision), `collect` (supervisor gathers callbacks; queue if busy, nothing lost).
- This is the A2A mesh made concrete: coalitions (`CoalitionWorkflow`) dispatch sub-agents onto the substrate; the blackboard is fed by `submit_result` callbacks.

## What it replaces / touches

- `cli_executors/claude_interactive.py`: the `subprocess.Popen` + `decide_pty_action` watchdog → a `TmuxController` client. The answer-file/silence machine is **deleted**, not tuned.
- `cli_runtime.py`: keep the simple non-interactive/headless path for print-mode utilities; the git-credential + SSH-key wiring (`apply_git_ssh`, `_apply_git_credential_env`) moves to session setup (set once per session, not per turn).
- `workflows.py` `execute_chat_cli`: dispatches `send_turn` against a (created-or-reused) session instead of spawning a process.
- `apps/mcp-server`: new `submit_result` / `request_input` (+ `assign`/`collect`) tools, agent-JWT-scoped.
- New: `session_substrate` table (Postgres) for durable session registry; Redis for liveness; Dockerfile adds `tmux` + `libtmux`.

## Phasing (cloud-first, incremental, each shippable)

- **P1 — Cloud pod substrate + interactive Claude as first client.** `TmuxController` (pod endpoint) + per-conversation session + Claude interactive REPL + `submit_result`/`request_input`. Delete the watchdog. **This alone fixes exit-143/freeze.**
- **P2 — All CLIs.** Codex/Gemini/Copilot/OpenCode turn-engine adapters over the same substrate.
- **P3 — Parallel sub-agents.** Panes/sessions fan-out + MCP inbox `assign`/`collect`; wire into A2A coalitions.
- **P4 — Local substrate.** `ap-broker` + the broker `SessionEndpoint`; Claudia-bridge becomes a broker client. Same protocol, deny-by-default profile.

## Pod-redeploy survival (open design point)

`code-worker` pods restart on every deploy; tmux sessions die with them. tmux-resurrect does **not** restore live agent state. So: the `session_substrate` registry + each CLI's own session id are the source of truth; on pod restart the substrate **re-creates** the tmux session and the per-CLI adapter resumes the CLI's conversation (`--resume`/`--continue` where supported) — the user sees continuity, the tmux session is disposable. Detail to settle in P1.

## Risks / open questions for the spec review

1. **MCP-callback reliability** — what if an agent ends its turn without calling `submit_result`? Mitigation: frame the MCP call as *the only way to deliver*; backstop with control-mode liveness + a bounded "no callback and pane idle at the REPL prompt" escalation that **asks**, never kills.
2. **Per-CLI interactive differences** — not every CLI's REPL injects/submits identically; the adapter boundary must absorb that without leaking into the substrate.
3. **Control-mode backpressure** — a chatty agent floods `%output`; need `refresh-client -f pause-after=N`.
4. **Pod-redeploy continuity** — the re-create-and-resume flow above.
5. **Subscription credit (2026-06-15)** — interactive avoids the new Agent-SDK credit pool; confirm interactive limits are unaffected.

## Verification discipline (the lesson from today)

Every completion/turn-boundary claim is bound to a **real signal** (MCP callback, control-mode event, process exit code) — never silence, never a timer, never a kill. And: **live-test before merge.** The exit-143 fix passed 70 unit tests and two reviews but failed the live pull because the core assumption wasn't live-verified first. This substrate's P1 gate is a live "pull my work repos" turn that completes and returns a real answer.
