# Claude Code interactive watchdog — stop killing long tool turns ("pull my work repos" → exit 143)

**Date:** 2026-06-01 · **Status:** Plan (for Codex + Luna review BEFORE implementing)
**Files:** `apps/code-worker/cli_executors/claude_interactive.py` (the `_decide` state machine), minor `claude.py`; plus `docker-compose.yml` + `helm/values/*` for the `ANTHROPIC_API_KEY` cleanup.

## Symptom
Interactive Claude Code (subscription / native-PTY auth) works for normal chat turns but dies with **CLI exit 143 (SIGTERM)** the moment it is asked to **"pull my work repos."** Codex and Gemini do the same pulls fine.

## Root cause (confirmed against deployed `origin/main`)
1. **Git auth is identical for Claude and Codex.** Both wire the gh token (`_apply_git_credential_env`) **and** the SSH key (`cli_runtime.apply_git_ssh`) into the per-turn env — `claude.py:507/521`, `codex.py:118/122`. So auth is **not** the cause. (Verified live this session: the SSH key clones `ustwo/nfl-minigames` fine via Codex.)
2. **The only difference is execution mode.** Subscription Claude is forced onto the **interactive PTY** path (`claude_interactive.py`); Codex/Gemini run **headless** and run to completion. Only the PTY has a freeze-watchdog.
3. **The watchdog's completion model is the bug.** A turn completes when Claude writes an **answer file**. In `_decide()` step 4b (lines ~319–334), the idle-`/exit` is suppressed only for the first **`first_output_seconds` (90s)** after submit:

   ```python
   if awaiting_answer_file:
       baseline = submitted_at if submitted_at is not None else start
       if now - baseline < first_output_seconds:   # 90s window
           return "wait"
   # Fallback (cap exceeded): legacy idle /exit
   if now - last_output >= idle_exit_seconds:
       return "exit"                                # → /exit → SIGTERM → exit 143
   return "wait"
   ```

   After 90s with no answer file yet, it reverts to the legacy idle path. **"Pull my work repos"** is a multi-repo clone that (a) takes **>90s** and (b) has **silent stretches during git network I/O ≥ `idle_exit_seconds`**. So ~90s in, a quiet network gap fires `/exit` and kills Claude mid-pull → exit 143. Short conversational turns write the answer file fast and never hit this. Codex/Gemini (headless) have no such loop.

## Fix
While **awaiting the answer file**, keep the turn alive as long as Claude is **still making progress** (output within a generous activity window), bounded by the outer 900s timeout — instead of hard-reverting to the short idle-`/exit` at the 90s mark.

Concretely, in `_decide()` 4b, replace the fixed 90s suppression with an **activity-based** window:

```python
if awaiting_answer_file:
    # Keep waiting while Claude is still emitting output (actively running
    # tools — e.g. a multi-repo git clone). Only the OUTER timeout + a generous
    # inactivity gap bound this; a fixed 90s-since-submit cap false-kills long
    # tool turns whose answer file legitimately lands minutes in.
    if now - last_output < long_task_idle_seconds:   # e.g. 120s, env-tunable
        return "wait"
# Fallback: truly idle (done-without-file or hung) → legacy idle /exit
if now - last_output >= idle_exit_seconds:
    return "exit"
return "wait"
```

- New knob `long_task_idle_seconds` (default ~120s, `CLAUDE_CODE_INTERACTIVE_LONGTASK_IDLE_SECONDS`) tolerates git network stalls. Still bounded by the outer 900s `_interactive_timeout`.
- **Unchanged:** the §3 startup-freeze gate (`post_submit_first_output_seconds`, 35s no-output-AT-ALL) and the trust/auto-update resend. Those only fire when **zero** post-submit bytes ever arrive — a working pull always emits tool output, so they never false-fire on it.

## Why this does NOT reintroduce the freezes #742–#744 fixed
- **Startup freeze** (banner painted, submit swallowed, zero post-submit output): still caught by the unchanged §3 35s gate.
- **Trust/permission redraw eats the submit:** still recovered by the unchanged §3 resend.
- **Genuinely hung mid-turn** (output stopped, no file): still killed — now after `long_task_idle_seconds` instead of `idle_exit_seconds`, still far under the 900s cap.
- **Only new behavior:** a turn STILL emitting output past 90s without a file is allowed to continue (previously killed). That is exactly — and only — the long-active-tool case.

## `ANTHROPIC_API_KEY` cleanup (related; requested)
We use OAuth/subscription, not the Anthropic API key. Today the worker has `ANTHROPIC_API_KEY` set and `claude.py` only pops it at the last moment — a footgun: any code path that misses the pop routes Claude to **Console (API) billing** instead of the Max subscription. Remove `ANTHROPIC_API_KEY` from the **code-worker** env (`docker-compose.yml` + `helm/values/agentprovision-code-worker.yaml` + `.env`), keeping the executor's defensive pop as belt-and-suspenders. **Caveat:** only safe because no api-key-billing tenants run on this worker — confirm before removing. (API-key tenants, if any, would need the key restored on a separate path.)

## Verification (post-deploy)
1. Interactive Claude: "pull my work repos" (the `ustwo` SSH repos) → clones complete, answer returned, **no exit 143**.
2. A normal short Luna turn still completes promptly (no latency regression).
3. A genuinely frozen process still dies fast (no 25-min hang) — simulate by killing Claude's event loop / a no-output launch.
4. `env | grep ANTHROPIC_API_KEY` empty in the worker; `claude auth status` still `loggedIn: true` via subscription.

## Open questions for Codex + Luna
1. Is `long_task_idle_seconds ≈ 120s` the right inactivity gap for git network stalls, or should it key off the **Temporal activity heartbeat** (which already proves liveness) instead of a wall-clock gap?
2. Should heavy git/coding turns route to the **code-task path** (CodeTaskWorkflow) rather than the interactive chat turn entirely (bigger, cleaner separation — but more work)?
3. Is there a cleaner completion signal than the answer-file (e.g. REPL prompt-returned + idle), so we don't depend on Claude reliably writing the file on long turns?
