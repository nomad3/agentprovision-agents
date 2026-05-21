# User-signal classifier activation — design

**Date:** 2026-05-21
**Status:** Draft. Sized for Simon's review before implementation.
**Context:** PR #653 (value-layer §10 PR 5) shipped the contract surface for `appraise_and_record_user_signal` in `apps/api/app/services/emotion_engine_io.py`, but no live caller wires `classify_user_signal → appraise_and_record_user_signal`. The dead-wire activation is intentionally a separate design pass because the hot-path latency cost is non-trivial.

## 1. Problem

For affect to actually track user turns:
1. `classify_user_signal(message)` runs Ollama (Gemma 4) to produce a PAD payload — measured ~1-2 s on Simon's M4 with the current model.
2. `appraise_and_record_user_signal(...)` does the value-layer consult + episode write.
3. Step 1 dominates the latency budget.

Adding either to the synchronous chat path would regress chat response time by ~1.5 s per turn — unacceptable given Tier-1 latency work already shipped (greeting fast-path, RL routing).

## 2. Constraints

- **Hot-path latency budget:** ≤ +10 ms per turn. No room for an inline Ollama call.
- **Affect arrives before the next turn:** the appraised vector must land on the episode before the *next* user message routes — so the prompt-side affect addendum reflects the most recent state.
- **Fail-open:** an Ollama outage or value-layer crash MUST NOT break chat. Existing emotion_engine IO already follows this discipline; the new caller must too.
- **Opt-in:** start behind a per-tenant feature flag (`user_signal_affect_enabled` on `tenant_features`), default `False`. Mirrors `value_layer_enabled` / `nightly_reflection_enabled`.

## 3. Options considered

| Option | Latency | Affect-before-next-turn | Implementation cost | Verdict |
|---|---|---|---|---|
| A. Sync inline before LLM dispatch | +1.5 s | yes | low | **rejected** — latency budget |
| B. Sync inline after LLM, before return | +1.5 s | yes | low | **rejected** — latency budget |
| C. Async via threading.Thread (mirror of `dispatch_post_chat_memory`) | +0 ms | usually yes | low | candidate |
| D. Temporal activity inside `PostChatMemoryWorkflow` | +0 ms | usually yes | medium (workflow edit + tests) | candidate |
| E. Push to Redis stream + orchestration-worker consumer | +0 ms | usually yes | high (new stream + worker) | rejected — overkill at our scale |
| F. RL-sampled sync (5% of turns) | +0.075 s avg | mostly no | medium | rejected — loses signal on 95% of turns |

C and D both work. Between them:

- **C** is a one-file change in `cli_session_manager.py` + the new dispatcher module. Pattern is already established for `PostChatMemoryWorkflow`. Fast to ship.
- **D** adds a new activity to the existing post-chat Temporal workflow. Better observability (Temporal UI shows retries + duration) but couples user_signal to the post-chat workflow, which already has its own retry/heartbeat budget. If user_signal classification gets slow, it could delay post-chat memory ingestion.

**Recommendation: Option C, with a follow-up to D once we have data on Ollama failure rates.**

## 4. Recommended design (Option C + F)

### 4.1 Feature flag

Migration 145 adds `tenant_features.user_signal_affect_enabled BOOLEAN NOT NULL DEFAULT FALSE`. Default OFF in prod. Operators flip it per tenant once we've verified the affect signal is useful for that tenant's persona.

### 4.2 Dispatcher

New module `apps/api/app/services/user_signal_dispatch.py`:

```python
def dispatch_user_signal_appraisal(
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    session_id: uuid.UUID,
    episode_id: uuid.UUID,
    user_text: str,
) -> None:
    """Fire-and-forget Ollama classify → episode write. Mirrors
    dispatch_post_chat_memory: background thread, no event-loop
    leakage, fail-open on any exception."""
    def _run():
        try:
            from app.services.user_signal_classifier import classify_user_signal
            from app.services.emotion_engine_io import (
                appraise_and_record_user_signal,
            )
            from app.db.session import SessionLocal
            payload = classify_user_signal(user_text)
            if payload is None:
                return  # classifier returned no signal — benign
            with SessionLocal() as db:
                appraise_and_record_user_signal(
                    db,
                    episode_id=episode_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    payload=payload,
                    user_text=user_text,
                )
        except Exception:
            logger.exception(
                "user_signal_dispatch: appraisal failed tenant=%s",
                tenant_id,
            )
    threading.Thread(target=_run, daemon=True).start()
```

A fresh SessionLocal is essential because the request's `db` is bound to the request thread and not safe to share. Same lesson as PostChatMemoryWorkflow.

### 4.3 Call site

`cli_session_manager.run_agent_session` after `_run_agent_session_legacy` returns and the metacog hook fires (so the response is already on the wire if streaming). Gate on the feature flag:

```python
if is_user_signal_affect_enabled(db, tenant_id=tenant_id):
    dispatch_user_signal_appraisal(
        tenant_id=tenant_id,
        agent_id=resolved_agent_id,
        session_id=session_id,
        episode_id=episode_id,
        user_text=message,
    )
```

`resolved_agent_id` and `episode_id` need to be plumbed; the existing tool-failure path already resolves them in `_record_tool_failure_affect`, so we reuse the same lookup.

### 4.4 Race conditions

Between user-signal appraise (fire-and-forget) and a tool-outcome appraise (same turn, sync inside cli_session_manager): both write to the same episode's `affect_vector`. Order is non-deterministic. Two writes per turn is fine — both are idempotent and produce the same shape; the second wins. The order doesn't matter for downstream consumers because the prompt-side reader (`build_affect_addendum_for_session`) reads at the *next* turn, by which time both writes have settled.

### 4.5 Observability

- `emotion_appraise_events_total{event_type="user_signal"}` increments (already present from PR 5).
- `emotion_user_signal_classify_duration_seconds` histogram — new. Tracks Ollama latency so we can move to Option D if the tail explodes.
- `emotion_user_signal_classify_failures_total{reason}` counter — tracks Ollama timeouts, empty responses, malformed JSON.

## 5. Implementation PRs

| PR | Scope |
|---|---|
| 1 | Migration 145 + `is_user_signal_affect_enabled` helper. Feature flag default OFF, model column. Unit test for kill-switch read. |
| 2 | `user_signal_dispatch.dispatch_user_signal_appraisal` + call site in `cli_session_manager`. Two new Prometheus metrics. |
| 3 | Operator UI tab on `AgentDetailPage` exposing the flag (or fold into the existing Values tab as a small toggle row). |

Each PR ships independently. PR 1 + 2 are needed to activate; PR 3 is operator ergonomics.

## 6. Open questions

1. **Should the dispatcher debounce per session?** A user typing fast can fire 3 classify calls in 2 seconds. Each is independent Ollama load. Phase 1 ships without debounce; if Ollama saturates we add a per-(session, last-2s) skip.
2. **What about peer_signal?** The emotion engine has a `peer_signal` event type for coalition turns. Not wired yet either. Same dispatcher pattern would apply; deferred to a separate design pass.
3. **Per-message-type sampling?** Greeting messages ("hola luna") probably don't need classification. Could skip the dispatch when the greeting fast-path fires. Phase 1.5 once we have data.

## 7. Status

**Awaiting Simon's go-ahead.** No code shipped from this design yet — it's a research note for review.
