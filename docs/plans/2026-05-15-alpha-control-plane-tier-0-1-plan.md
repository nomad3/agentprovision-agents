# Alpha Control Plane — Tier 0–1 Implementation Plan

**Date:** 2026-05-15
**Design doc:** `docs/plans/2026-05-15-alpha-control-plane-design.md` (rev 2b, APPROVED)
**Scope:** smallest shippable cockpit — chat + integrations rail at `/cockpit` with the persistence + tier infrastructure that all higher tiers depend on
**Owner:** session goal `/goal run the spec reviewer, code reviewer, tests write the plan, execute the plan…`

---

## 0. Goals & non-goals

### Goals (must ship in this slice)

1. `/cockpit` route accessible to all users; renders 3-zone shell skeleton.
2. Conversation works at tier 0 (chat with alpha, replies stream in).
3. Integrations rail visible at tier 1, populated with the user's connected integrations.
4. Backend persists every session event in a new `session_events` table.
5. Backend exposes `/api/v2/sessions/{id}/events` (SSE live + paginated replay).
6. Tier picker UI sets `user_preferences.alpha_cockpit_tier`; the JWT carries it for fast reads.
7. Existing `ChatPage.js` keeps working unchanged (v1 endpoint frozen).

### Non-goals (tier 2+ specs)

- Plan stepper, tool-call inline cards, sub-agent dispatch UI, live terminal drawer rendering.
- Right-panel context library (right panel exists at tier 0–1 but renders a "no context" placeholder).
- Resource browsers beyond `integrations` (memory / projects / leads / datasets / experiments / entities are tier 2+).
- Auto-quality scoring surfaces (tier 4).
- Coalition replay live view (tier 2+).
- CLI `alpha attach` command (out of scope until tier 0 GUI is verified).
- Migration of `ChatPage.js` consumers to v2 (v1 stays as-is).

---

## 1. Architecture refresher (from design doc)

```
┌────────────────────────────────────────────────────────────┐
│  CHANNELS                                                  │
│  alpha CLI (deferred) │ Web (this PR) │ Tauri (this PR)    │
│                       │ WhatsApp (unchanged)                │
└────────────────────────────────────────────────────────────┘
                              ↕  /api/v2/sessions/{id}/events
┌────────────────────────────────────────────────────────────┐
│  EVENT BUS                                                 │
│  publish_session_event (extended)                          │
│    → INSERT session_events (Postgres, seq_no)              │
│    → THEN publish Redis (existing fan-out)                 │
└────────────────────────────────────────────────────────────┘
                              ↕
┌────────────────────────────────────────────────────────────┐
│  KERNEL (unchanged: api / orchestration-worker / code-worker)│
└────────────────────────────────────────────────────────────┘
```

---

## 2. Work breakdown — 7 commits, 7 PRs (chained)

Each section below maps to one PR. PRs chain (PR2 base = PR1, PR3 base = PR2, …) per `feedback_chain_pr_branches.md`.

### §1. PR-1 — `session_events` table migration

**Branch:** `feat/cockpit-tier01-01-session-events-migration`
**Base:** `main`
**Touches:** `apps/api/migrations/`, `apps/api/app/models/`

#### Files

- `apps/api/migrations/133_session_events.sql` (new) — schema below
- `apps/api/app/models/session_event.py` (new) — SQLAlchemy model

#### Schema

```sql
CREATE TABLE session_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  tenant_id    UUID NOT NULL,
  seq_no       BIGINT NOT NULL,
  event_type   VARCHAR(64) NOT NULL,
  payload      JSONB NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (session_id, seq_no)
);
CREATE INDEX idx_session_events_session_seq ON session_events(session_id, seq_no);
CREATE INDEX idx_session_events_tenant_created ON session_events(tenant_id, created_at);
```

#### Retention

Add cron in `apps/api/app/services/jobs/` or extend existing maintenance job:
```sql
DELETE FROM session_events WHERE created_at < NOW() - INTERVAL '30 days';
```

Run daily at low-traffic hour. Indefinite retention exception: `event_type = 'auto_quality_score'` (rows are not deleted).

#### Tests

- `apps/api/tests/migrations/test_133_session_events.py` — migration applies cleanly, indexes exist, unique constraint enforced.

#### Acceptance

- Migration runs in <5s against the local db.
- Inserting 1000 events for a session and re-applying the `seq_no` allocation yields no duplicate-key violations.

---

### §2. PR-2 — `publish_session_event` dual-write

**Branch:** `feat/cockpit-tier01-02-publish-dual-write` (off PR-1)
**Touches:** `apps/api/app/services/collaboration_events.py`

#### Logic

```python
def publish_session_event(session_id: str, event_type: str, payload: dict, *, tenant_id: str | None = None) -> dict:
    """Persist + fan out. Returns the envelope with allocated seq_no + event_id.

    Failure ordering:
      * Postgres INSERT fails → raise; Redis publish skipped.
      * Postgres commits, Redis publish fails → log warning; replay covers it.
    """
    db = SessionLocal()
    try:
        # Per-session advisory lock; auto-released at COMMIT/ROLLBACK.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:sid))"), {"sid": str(session_id)})
        seq_no = db.execute(
            text("SELECT COALESCE(MAX(seq_no), 0) + 1 FROM session_events WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar()
        envelope = {
            "event_id": str(uuid.uuid4()),
            "session_id": str(session_id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "ts": datetime.utcnow().isoformat(),
            "type": event_type,
            "seq_no": seq_no,
            "payload": payload,
        }
        db.add(SessionEvent(
            id=envelope["event_id"], session_id=session_id, tenant_id=tenant_id,
            seq_no=seq_no, event_type=event_type, payload=payload,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Best-effort live fan-out. Failure does not raise.
    try:
        redis_client.publish(f"session:{session_id}", json.dumps(envelope))
    except Exception as exc:
        logger.warning("Redis publish failed for session=%s event=%s: %s",
                       session_id, envelope["event_id"], exc)

    return envelope
```

Existing callers continue to call `publish_session_event(...)` — signature backward-compatible (the new `tenant_id` kwarg is optional; first-pass keeps `tenant_id=None` until callers are updated).

#### Tests

- `apps/api/tests/services/test_publish_session_event_dual_write.py`:
  - Happy path: row persists with monotonic seq_no.
  - Concurrent publishers in same session don't duplicate seq_no (use a threading harness with 20 parallel publishers).
  - Postgres failure: caller sees exception, no Redis publish.
  - Redis failure: caller sees no exception, log warning, row still persisted.
  - Cross-session writes don't contend.

#### Acceptance

- 100 parallel publishers across 10 sessions complete with no duplicate `(session_id, seq_no)` rows.

---

### §3. PR-3 — `/api/v2/sessions/{id}/events` endpoints

**Branch:** `feat/cockpit-tier01-03-v2-events-endpoint` (off PR-2)
**Touches:** `apps/api/app/api/v2/__init__.py` (new), `apps/api/app/api/v2/session_events.py` (new), `apps/api/main.py` (mount v2 router)

#### SSE endpoint

```
GET /api/v2/sessions/{session_id}/events
Accept: text/event-stream
```

Streams events as they arrive on Redis `session:{session_id}` channel. Each event is the full envelope (§2 schema). Subscribes via Redis pubsub.

#### Replay endpoint

```
GET /api/v2/sessions/{session_id}/events?since=<seq_no>&limit=<n>
```

- `limit` default 100, max 500.
- Returns `{events: [...], next_cursor: <seq_no | null>, latest_seq_no: <seq_no>}`.
- If `since` is older than 24h, returns `409 Conflict` with `{error: "replay_window_expired", latest_seq_no}`.
- Coalesces `cli_subprocess_stream` events: groups consecutive same-platform events within 5-second windows into one synthetic event with `payload.coalesced_count` and `payload.chunks[]` (last 3 chunks only).

#### Tests

- `apps/api/tests/api/v2/test_session_events.py`:
  - Replay returns events ordered by seq_no.
  - Pagination via `next_cursor` works.
  - `since` older than 24h returns 409.
  - Subprocess stream coalescing collapses 50 chunks in 5s to 1 event.
  - SSE connection delivers live events end-to-end (publish via fixture, assert receive).

#### Acceptance

- Replay returns 100 events in <200ms p95 on a 30k-event session.

---

### §4. PR-4 — user tier service + endpoint

**Branch:** `feat/cockpit-tier01-04-user-tier-service` (off PR-3)
**Touches:** `apps/api/app/services/user_tier.py` (new), `apps/api/app/api/v1/users.py` (new endpoint), `apps/api/app/core/security.py` (JWT minting includes tier)

#### Service

```python
# apps/api/app/services/user_tier.py
_PREFERENCE_TYPE = "alpha_cockpit_tier"
VALID_TIERS = {0, 1, 2, 3, 4, 5}

def get_tier(db, user_id: UUID, tenant_id: UUID) -> int:
    row = db.query(UserPreference).filter_by(
        user_id=user_id, tenant_id=tenant_id, preference_type=_PREFERENCE_TYPE
    ).first()
    if not row or not row.value:
        return 0
    try:
        tier = int(row.value)
        return tier if tier in VALID_TIERS else 0
    except (TypeError, ValueError):
        return 0

def set_tier(db, user_id: UUID, tenant_id: UUID, tier: int) -> int:
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier {tier}; must be 0..5")
    row = db.query(UserPreference).filter_by(
        user_id=user_id, tenant_id=tenant_id, preference_type=_PREFERENCE_TYPE
    ).first()
    if row:
        row.value = str(tier)
        row.updated_at = datetime.utcnow()
    else:
        db.add(UserPreference(
            user_id=user_id, tenant_id=tenant_id,
            preference_type=_PREFERENCE_TYPE, value=str(tier),
        ))
    db.commit()
    return tier
```

#### Endpoint

```
PUT /api/v1/users/me/cockpit-tier  {tier: 0..5}
GET /api/v1/users/me/cockpit-tier      → {tier: int}
```

Both authenticated via the standard user JWT dependency.

#### JWT

When the API mints a JWT (login, refresh), include `cockpit_tier: int` claim. SPAs read from JWT for cheap reads; on tier change, the SPA optimistically updates local state AND the next JWT refresh carries the new value.

#### Tests

- `apps/api/tests/services/test_user_tier.py`: get default 0, set then get, invalid tier rejected, unicode/None value coerces to 0.
- `apps/api/tests/api/v1/test_user_tier_endpoint.py`: PUT/GET happy path, PUT rejects tier 6 / negative / non-int, tenant isolation (other tenant's user can't read).

---

### §5. PR-5 — `/cockpit` route + 3-zone shell scaffold

**Branch:** `feat/cockpit-tier01-05-cockpit-shell` (off PR-4)
**Touches:** `apps/web/src/cockpit/` (new directory)

#### File layout

```
apps/web/src/cockpit/
  index.js                  # exports CockpitPage as default
  CockpitPage.js            # /cockpit route entry, owns session selection
  CockpitShell.js           # 3-zone CSS grid layout
  CockpitShell.module.css
  LeftRail.js               # icon strip; tier-gated rendering
  CenterConversation.js     # the alpha chat thread
  RightPanel.js             # placeholder at tier 0–1
  TerminalDrawer.js         # placeholder at tier 0–1 (hidden)
  tierFeatures.js           # TIER_FEATURES map (§6)
  useTier.js                # hook (§6)
  TierGate.js               # wrapper component (§6)
  hooks/
    useSessionEvents.js     # subscribe to /api/v2/sessions/{id}/events
    useSession.js           # current session id from URL or last-active
```

#### Shell layout (CSS grid)

```css
.shell {
  display: grid;
  grid-template-columns: var(--rail-width, 48px) 1fr var(--right-width, 0px);
  grid-template-rows: 1fr var(--drawer-height, 0px);
  height: 100vh;
}
```

Right column width 0 at tier 0; expands at tier 1+ to 380px. Drawer height 0 at tier 0–1; expands at tier 2+.

#### Router

`apps/web/src/App.js` adds `<Route path="/cockpit" element={<CockpitPage />} />` lazy-imported.

#### Tests

- `apps/web/src/cockpit/__tests__/CockpitPage.test.js`:
  - Renders without crashing at tier 0.
  - Renders left rail at tier 1.
  - Right panel is hidden (`display: none` or width 0) at tier 0–1.
  - Drawer is hidden at tier 0–1.

---

### §6. PR-6 — `useTier` + `TierGate` + tier picker

**Branch:** `feat/cockpit-tier01-06-tier-gating` (off PR-5)
**Touches:** `apps/web/src/cockpit/tierFeatures.js`, `useTier.js`, `TierGate.js`, settings UI

#### `tierFeatures.js` (literal capability map)

```js
export const TIER_FEATURES = {
  0: { showRail: false, showRightPanel: false, showDrawer: false,
       showPlanStepper: false, showPalette: false,
       allowedRailIcons: [] },
  1: { showRail: true, showRightPanel: false, showDrawer: false,
       showPlanStepper: false, showPalette: false,
       allowedRailIcons: ['integrations', 'memory'] },
  2: { showRail: true, showRightPanel: true, showDrawer: false,
       showPlanStepper: true, showPalette: false,
       allowedRailIcons: ['integrations', 'memory', 'projects'] },
  3: { showRail: true, showRightPanel: true, showDrawer: false,
       showPlanStepper: true, showPalette: true,
       allowedRailIcons: ['integrations', 'memory', 'projects', 'leads',
                          'datasets', 'experiments', 'entities', 'skills'] },
  4: { showRail: true, showRightPanel: true, showDrawer: true,
       showPlanStepper: true, showPalette: true, showAutoQualityScore: true,
       allowedRailIcons: ['integrations', 'memory', 'projects', 'leads',
                          'datasets', 'experiments', 'entities', 'skills',
                          'fleet', 'deployments', 'rl'] },
  5: { showRail: true, showRightPanel: true, showDrawer: true,
       showPlanStepper: true, showPalette: true, showAutoQualityScore: true,
       showWorkflowEditor: true, showSkillAuthor: true, showPolicyEditor: true,
       allowedRailIcons: ['integrations', 'memory', 'projects', 'leads',
                          'datasets', 'experiments', 'entities', 'skills',
                          'fleet', 'deployments', 'rl'] },
};

export function getCapabilities(tier) {
  return TIER_FEATURES[Math.max(0, Math.min(5, tier ?? 0))];
}
```

#### `useTier.js`

```js
import { useCallback, useEffect, useState } from 'react';
import { decodeJwt } from '../utils/jwt';
import api from '../services/api';

export function useTier() {
  const [tier, setTierState] = useState(() => {
    const token = localStorage.getItem('jwt');
    return token ? (decodeJwt(token)?.cockpit_tier ?? 0) : 0;
  });

  useEffect(() => {
    // First mount: confirm with server in case JWT is stale.
    api.get('/users/me/cockpit-tier')
      .then(res => setTierState(res.data.tier))
      .catch(() => { /* swallow; JWT value stands */ });
  }, []);

  const setTier = useCallback(async (next) => {
    await api.put('/users/me/cockpit-tier', { tier: next });
    setTierState(next);
    // Schedule a JWT refresh so subsequent reloads see the new tier.
    api.post('/auth/refresh');  // best-effort
  }, []);

  return [tier, setTier];
}
```

#### `TierGate.js`

```jsx
export function TierGate({ min, fallback = null, children }) {
  const [tier] = useTier();
  if (tier < min) return fallback;
  return children;
}
```

#### Picker UI

A new settings panel `apps/web/src/cockpit/TierPicker.js` rendered in the cockpit settings menu (and inline as part of first-touch tier 0 welcome card). Six radio cards (tier 0 through 5) with one-line examples. Hitting "Save" calls `setTier(newTier)`.

#### Tests

- `apps/web/src/cockpit/__tests__/useTier.test.js`: reads from JWT on mount, syncs with server, set persists.
- `apps/web/src/cockpit/__tests__/TierGate.test.js`: renders children when tier ≥ min; falls back otherwise.
- `apps/web/src/cockpit/__tests__/TierPicker.test.js`: 6 cards rendered, current tier highlighted, change triggers PUT.

---

### §7. PR-7 — integration + e2e + code-review polish

**Branch:** `feat/cockpit-tier01-07-integration` (off PR-6)
**Touches:** ties everything together; minor polish from review findings

- Wire `CenterConversation` to existing chat endpoints (POST user message, subscribe to v2 SSE for replies). Existing `ChatPage.js` untouched.
- LeftRail at tier 1 renders Integrations icon — click opens existing IntegrationsPanel as overlay (deferred: inline-rail integration, that's tier 2+).
- Cockpit settings menu includes Tier Picker.
- e2e Playwright spec: load `/cockpit`, send a message at tier 0, verify reply renders. Switch to tier 1, verify rail appears. Switch to tier 4, verify drawer + extra icons appear (drawer empty since no subprocess events).
- Dispatch `superpowers:code-reviewer` against the final PR + apply findings.

---

## 3. Cross-cutting concerns

### Build budget

- Local deploys per PR: api + web + possibly orchestration-worker (depending on which PR). Per PR, the changed-services detection (PR #475's fix) picks the right subset.
- Disk budget: each rebuild adds ~500-800 MB until docker layer cache stabilises. With 76 GB free starting baseline (host disk), 7 PRs × cold rebuild estimate is comfortably within budget. Prune `docker builder prune -a -f` between PRs if Build Cache exceeds 5 GB.

### Docker safety guardrails (per goal directive)

- Check `docker system df` before each PR push; prune builder if >5 GB reclaimable.
- Never `docker volume prune` (per memory `docker_disk_full_recovery.md`).
- If host disk drops below 30 GB free at any point, stop and prune before pushing.
- The auto-prune sentinel that caused disk-full-cascade-earlier-this-session is killed; we manage prune manually per PR.

### Convention adherence (per goal directive)

- Plans + docs in `docs/plans/` and `docs/superpowers/specs/`, never repo root.
- Each PR gets a one-paragraph plan doc cross-referencing this master plan.
- All PRs assigned to `nomad3`.
- No `Co-Authored-By: Claude` in commits or PR bodies.
- Chain PRs via `--base` to prior PR's branch.

### Drift prevention (per CLAUDE.md)

- No helm/terraform changes anticipated (cockpit is web-only + api migrations).
- If migrations land that affect helm/terraform later, update both in the same PR.

---

## 4. Acceptance for the slice

The Tier 0–1 slice is "done" when:

1. A new user signs up → lands on `/cockpit` at tier 0 → can chat with alpha → message + reply persist as `chat_message` events in `session_events`.
2. User picks tier 1 in settings → left rail appears with Integrations icon → clicking opens IntegrationsPanel overlay.
3. User picks tier 4 → drawer + extra rail icons appear (drawer empty until tier 2+ adds subprocess events; this is fine).
4. Existing `ChatPage.js` at `/chat` continues to work unchanged.
5. All 7 PRs merged with green CI.
6. Code-review subagent run on PR-7 returns CLEAN (or all findings fixed in same PR).
7. README + CLAUDE.md + relevant memory notes updated with ASCII diagrams of the new architecture (separate task #218).
8. Host disk free ≥ baseline-minus-5GB at the end (no disk regressions from builds).

---

## 5. Out of scope (next planning cycle)

- Tier 2 plan: plan stepper inline, right-panel context library, sub-agent cards, terminal drawer rendering, full coalition live view.
- Tier 3 plan: full resource browsers, Cmd+K palette, pinning, multi-pin context strip.
- Tier 4 plan: fleet/deployments/RL surfaces, drawer-on-by-default, auto-quality score viz.
- Tier 5 plan: workflow editor, skill author, policy editor.
- CLI viewport: `alpha attach`, channel-side event filter, ANSI rendering.

Each gets its own design doc + plan when its turn comes.

---

## References

- Design doc (this slice implements): `docs/plans/2026-05-15-alpha-control-plane-design.md` (rev 2b, APPROVED)
- Existing: `apps/api/app/services/collaboration_events.py`, `apps/api/app/api/v1/chat.py`, `apps/api/app/models/user_preference.py`, `apps/web/src/pages/ChatPage.js`
- Convention memories: `feedback_pr_workflow.md`, `feedback_chain_pr_branches.md`, `feedback_verify_branch_before_commit.md`, `feedback_address_all_review_findings.md`, `docker_disk_full_recovery.md`
