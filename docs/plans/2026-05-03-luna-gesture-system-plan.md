# Luna Gesture System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hand gestures the primary interaction modality for the Luna Tauri client, replacing mouse/trackpad for daily ops (navigation, scroll, click, agent switch, memory recall, workflow control), with Apple-trackpad grammar (finger-count + motion) plus Luna extensions, wake-gesture activated, Rust-native engine inside the existing Tauri main process.

**Architecture:** In-process Rust gesture engine inside `apps/luna-client/src-tauri/` owning AVFoundation camera + landmark extraction (Apple Vision primary, MediaPipe fallback). React `GestureProvider` consumes Tauri events and dispatches actions via existing API/MCP/skill paths. Bindings persisted to existing `user_preferences` table (extended with JSONB column). Audit + RL via existing `memory_activity` and `rl_experience_service`.

**Tech Stack:** Rust (Tauri 2, tokio, nokhwa, swift-bridge for Apple Vision FFI, enigo for cursor), React 18 (existing context-provider pattern), FastAPI/SQLAlchemy (extending existing `users.py` + `user_preferences` table), Postgres (manual SQL migration 114), pytest + Vitest + cargo test.

**Spec:** [`docs/plans/2026-05-03-luna-gesture-system-design.md`](./2026-05-03-luna-gesture-system-design.md)

**Branch:** `feat/luna-gesture-system` (already open with the design committed)

**Conventions to follow throughout:**
- Build via CI only (push to branch → GitHub Actions). Never `cargo build` or `tauri build` locally.
- All API code uses synchronous SQLAlchemy + the existing `deps.get_current_active_user`.
- Tauri commands use `#[tauri::command] async fn ... -> Result<T, String>` and `lazy_static! AtomicBool` for run-state — mirror the existing `CAPTURE_RUNNING` pattern in `lib.rs`.
- Rust modules go inside `apps/luna-client/src-tauri/src/gesture/`, registered in `lib.rs`. **No new cargo crate, no separate binary.**
- React components co-located in `apps/luna-client/src/components/gestures/`. Hooks under `apps/luna-client/src/hooks/`.
- Every task ends with a commit. Use Conventional Commits: `feat(luna):`, `feat(api):`, `test(luna):`, `chore(migrations):`, etc. **Never include `Co-Authored-By: Claude`** (per global CLAUDE.md).

---

## File map

### New files

```
apps/api/migrations/114_user_preferences_value_json.sql
apps/api/migrations/114_user_preferences_value_json.down.sql
apps/api/app/services/gesture_bindings_service.py
apps/api/app/schemas/gesture_binding.py
apps/api/tests/test_gesture_bindings.py

apps/luna-client/src-tauri/src/gesture/mod.rs
apps/luna-client/src-tauri/src/gesture/camera.rs
apps/luna-client/src-tauri/src/gesture/landmark.rs
apps/luna-client/src-tauri/src/gesture/landmark_apple_vision.rs
apps/luna-client/src-tauri/src/gesture/pose.rs
apps/luna-client/src-tauri/src/gesture/motion.rs
apps/luna-client/src-tauri/src/gesture/wake.rs
apps/luna-client/src-tauri/src/gesture/recognizer.rs
apps/luna-client/src-tauri/src/gesture/supervisor.rs
apps/luna-client/src-tauri/src/gesture/cursor.rs
apps/luna-client/src-tauri/src/gesture/types.rs
apps/luna-client/src-tauri/src/gesture/tests/  (Rust unit tests)
apps/luna-client/src-tauri/swift/HandLandmarker.swift   (Apple Vision FFI helper)

apps/luna-client/src/context/GestureContext.jsx
apps/luna-client/src/hooks/useGesture.js
apps/luna-client/src/hooks/useGestureBindings.js
apps/luna-client/src/components/gestures/GestureOverlay.jsx
apps/luna-client/src/components/gestures/GestureBindingsPage.jsx
apps/luna-client/src/components/gestures/GestureBindingRow.jsx
apps/luna-client/src/components/gestures/GestureRecorder.jsx
apps/luna-client/src/components/gestures/GestureCalibration.jsx
apps/luna-client/src/components/luna/LunaCursor.jsx
apps/luna-client/src/components/gestures/defaults.js  (default bindings constant)
apps/luna-client/src/components/gestures/__tests__/GestureContext.test.jsx
apps/luna-client/src/components/gestures/__tests__/useGestureBindings.test.js
apps/luna-client/src/components/gestures/__tests__/GestureBindingsPage.test.jsx
```

### Modified files

```
apps/api/app/models/user_preference.py            # add value_json column
apps/api/app/api/v1/users.py                      # add /me/gesture-bindings endpoints
apps/api/app/services/rl_experience_service.py    # add 'gesture_action' to DECISION_POINTS
apps/api/app/services/memory_activity.py          # docstring: note 'gesture_triggered' event_type

apps/luna-client/src-tauri/src/lib.rs             # register gesture module + commands; rewrite start_spatial_capture as consumer; tray + shortcut additions
apps/luna-client/src-tauri/Cargo.toml             # add nokhwa, enigo, image, swift-bridge, futures dependencies
apps/luna-client/src-tauri/tauri.conf.json        # add NSAccessibilityUsageDescription, capability for gesture commands
apps/luna-client/src-tauri/build.rs               # swift-bridge codegen for HandLandmarker

apps/luna-client/src/App.jsx                      # wrap with GestureProvider; add /settings/gestures route
apps/luna-client/src/api.js                       # add getGestureBindings / saveGestureBindings
apps/luna-client/src/components/spatial/KnowledgeNebula.jsx  # migrate from luna-gesture-move event to useGesture()
apps/luna-client/src/components/spatial/GestureController.jsx  # DELETE in Phase 1 Task 1.14

apps/web/src/pages/SettingsPage.js                # add read-only Gestures subsection
```

---

# Phase 1 — Engine + grammar (week 1)

**Phase goal:** Default bindings work end-to-end. Open-palm wake-gesture arms the engine, 3-finger swipe up opens HUD, all default gestures fire actions, and the existing `KnowledgeNebula` 3D scene still works (migrated to the new event source). Sleeping <3% CPU, Armed <12% CPU. No `luna-gesture-move` listeners remain.

**Phase exit gate:** Code review subagent approves Phase 1 commits + manual smoke-test runbook completes on a Mac M4. PR opened (still draft).

## Task 1.1: Migration 114 — extend `user_preferences` with `value_json`

**Why:** Bindings serialize to JSON >200 chars; the existing `value VARCHAR(200)` column can't hold them. Reuses the existing prefs table per the spec's reuse map.

**Files:**
- Create: `apps/api/migrations/114_user_preferences_value_json.sql`
- Create: `apps/api/migrations/114_user_preferences_value_json.down.sql`
- Modify: `apps/api/app/models/user_preference.py`

- [ ] **Step 1: Write up migration SQL**

```sql
-- 114_user_preferences_value_json.sql
ALTER TABLE user_preferences
  ADD COLUMN IF NOT EXISTS value_json JSONB NULL;

ALTER TABLE user_preferences
  ADD CONSTRAINT user_preferences_value_json_size_cap
  CHECK (value_json IS NULL OR octet_length(value_json::text) <= 65536);

ALTER TABLE user_preferences
  ALTER COLUMN value DROP NOT NULL;

COMMENT ON COLUMN user_preferences.value_json IS
  'Optional rich JSON payload for preferences that exceed the 200-char value column. Capped at 64KB.';

INSERT INTO _migrations (filename, applied_at)
VALUES ('114_user_preferences_value_json.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
```

```sql
-- 114_user_preferences_value_json.down.sql
-- Backfill any NULLs first to satisfy the NOT NULL restoration
UPDATE user_preferences SET value = '' WHERE value IS NULL;

ALTER TABLE user_preferences
  ALTER COLUMN value SET NOT NULL;

ALTER TABLE user_preferences
  DROP CONSTRAINT IF EXISTS user_preferences_value_json_size_cap;

ALTER TABLE user_preferences
  DROP COLUMN IF EXISTS value_json;

DELETE FROM _migrations WHERE filename = '114_user_preferences_value_json.sql';
```

- [ ] **Step 2: Force-add the SQL files (project gitignore rule)**

Per the memory `migration_apply_pattern.md`, `*.sql` is in the global gitignore. Use `-f`:

```bash
git add -f apps/api/migrations/114_user_preferences_value_json.sql
git add -f apps/api/migrations/114_user_preferences_value_json.down.sql
```

- [ ] **Step 3: Update SQLAlchemy model**

Modify `apps/api/app/models/user_preference.py`:

```python
"""User Preference — learned or explicit communication preferences."""
import uuid
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    preference_type = Column(String(50), nullable=False)
    value = Column(String(200), nullable=True)  # nullable as of migration 114; rich payloads use value_json
    value_json = Column(JSONB, nullable=True)
    confidence = Column(Float, default=0.5)
    evidence_count = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: Apply locally and verify**

Apply migration via the active local-runtime path (docker-compose per `deployment_current_state.md`):

```bash
docker compose exec -T db psql -U postgres -d agentprovision \
  -f /tmp/114.sql < apps/api/migrations/114_user_preferences_value_json.sql
```

Or if using K8s pod path:

```bash
PG_POD=$(kubectl get pod -n agentprovision -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}')
kubectl cp apps/api/migrations/114_user_preferences_value_json.sql agentprovision/$PG_POD:/tmp/114.sql
kubectl exec -n agentprovision $PG_POD -- psql -U postgres agentprovision -f /tmp/114.sql
```

Verify column:

```bash
docker compose exec -T db psql -U postgres -d agentprovision -c "\\d user_preferences" | grep value_json
```

Expected: `value_json | jsonb |`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/models/user_preference.py
git commit -m "chore(migrations): 114 — extend user_preferences with value_json JSONB for rich preferences"
```

---

## Task 1.2: Pydantic schemas for gesture bindings

**Why:** Strong validation at the API boundary. List-of-bindings cap of 100, payload cap 64KB, restricted action/pose enums.

**Files:**
- Create: `apps/api/app/schemas/gesture_binding.py`

- [ ] **Step 1: Write the failing test stub**

Create `apps/api/tests/test_gesture_bindings.py` with import + a single failing test. Full test contents come in Task 1.4; this just establishes the test file:

```python
import pytest
from app.schemas.gesture_binding import Binding, BindingsPayload, ActionKind, Pose


def test_binding_rejects_unknown_action_kind():
    with pytest.raises(Exception):
        Binding(
            id="b1",
            gesture={"pose": "open_palm"},
            action={"kind": "definitely_not_real"},
            scope="global",
            enabled=True,
            user_recorded=False,
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_gesture_bindings.py::test_binding_rejects_unknown_action_kind -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.gesture_binding'`.

- [ ] **Step 3: Write the schema**

Create `apps/api/app/schemas/gesture_binding.py`:

```python
"""Gesture binding schemas — validates gesture-to-action bindings sent from Luna client."""
from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, conlist


class Pose(str, Enum):
    OPEN_PALM = "open_palm"
    FIST = "fist"
    POINT = "point"
    PEACE = "peace"
    THREE = "three"
    FOUR = "four"
    FIVE = "five"
    THUMB_UP = "thumb_up"
    PINCH_POSE = "pinch_pose"
    ROTATION_POSE = "rotation_pose"
    CUSTOM = "custom"


class ActionKind(str, Enum):
    MEMORY_RECALL = "memory_recall"
    MEMORY_RECORD = "memory_record"
    MEMORY_CLEAR = "memory_clear"
    NAV_CHAT = "nav_chat"
    NAV_HUD = "nav_hud"
    NAV_COMMAND_PALETTE = "nav_command_palette"
    NAV_BINDINGS = "nav_bindings"
    AGENT_NEXT = "agent_next"
    AGENT_PREV = "agent_prev"
    AGENT_OPEN = "agent_open"
    WORKFLOW_RUN = "workflow_run"
    WORKFLOW_PAUSE = "workflow_pause"
    WORKFLOW_DISMISS = "workflow_dismiss"
    APPROVE = "approve"
    DISMISS = "dismiss"
    MIC_TOGGLE = "mic_toggle"
    PTT_START = "ptt_start"
    PTT_STOP = "ptt_stop"
    SCROLL_UP = "scroll_up"
    SCROLL_DOWN = "scroll_down"
    SCROLL_LEFT = "scroll_left"
    SCROLL_RIGHT = "scroll_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    CURSOR_MOVE = "cursor_move"
    CLICK = "click"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    CUSTOM = "custom"


class GestureSpec(BaseModel):
    pose: Pose
    motion: Optional[dict] = None  # { kind, direction }
    modifier_pose: Optional[Pose] = None


class ActionSpec(BaseModel):
    kind: ActionKind
    params: Optional[dict] = None


class Binding(BaseModel):
    id: str = Field(..., max_length=64)
    gesture: GestureSpec
    action: ActionSpec
    scope: Literal["global", "luna_only", "hud_only", "chat_only"]
    enabled: bool = True
    user_recorded: bool = False


class BindingsPayload(BaseModel):
    bindings: conlist(Binding, max_length=100)


class BindingsResponse(BaseModel):
    bindings: List[Binding]
    updated_at: Optional[str] = None
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd apps/api && pytest tests/test_gesture_bindings.py::test_binding_rejects_unknown_action_kind -v
```
Expected: PASS.

- [ ] **Step 5: Add positive-case test + run**

Append to `tests/test_gesture_bindings.py`:

```python
def test_binding_accepts_valid_payload():
    payload = BindingsPayload(bindings=[
        Binding(
            id="b1",
            gesture=GestureSpec(pose=Pose.OPEN_PALM),
            action=ActionSpec(kind=ActionKind.NAV_HUD),
            scope="global",
        )
    ])
    assert len(payload.bindings) == 1
    assert payload.bindings[0].action.kind == ActionKind.NAV_HUD


def test_binding_rejects_too_many():
    with pytest.raises(Exception):
        BindingsPayload(bindings=[
            Binding(
                id=f"b{i}",
                gesture=GestureSpec(pose=Pose.OPEN_PALM),
                action=ActionSpec(kind=ActionKind.NAV_HUD),
                scope="global",
            )
            for i in range(101)
        ])
```

Add the missing import line at the top: `from app.schemas.gesture_binding import GestureSpec, ActionSpec`.

Run: `pytest tests/test_gesture_bindings.py -v` → 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/schemas/gesture_binding.py apps/api/tests/test_gesture_bindings.py
git commit -m "feat(api): pydantic schema for gesture bindings (validation, 100-binding cap)"
```

---

## Task 1.3: `gesture_bindings_service.py` (CRUD over `user_preferences`)

**Files:**
- Create: `apps/api/app/services/gesture_bindings_service.py`

- [ ] **Step 1: Write failing test**

Append to `apps/api/tests/test_gesture_bindings.py`:

```python
def test_service_round_trip(db_session, test_user):
    from app.services.gesture_bindings_service import (
        get_bindings_for_user, save_bindings_for_user
    )
    bindings = [
        Binding(
            id="b1",
            gesture=GestureSpec(pose=Pose.OPEN_PALM),
            action=ActionSpec(kind=ActionKind.NAV_HUD),
            scope="global",
        ).model_dump(mode="json")
    ]
    save_bindings_for_user(db_session, test_user.tenant_id, test_user.id, bindings)
    loaded = get_bindings_for_user(db_session, test_user.tenant_id, test_user.id)
    assert len(loaded) == 1
    assert loaded[0]["action"]["kind"] == "nav_hud"
```

(`db_session` and `test_user` fixtures are already established in `apps/api/tests/conftest.py`.)

- [ ] **Step 2: Run test to verify fail**

```bash
pytest tests/test_gesture_bindings.py::test_service_round_trip -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the service**

Create `apps/api/app/services/gesture_bindings_service.py`:

```python
"""Service for reading/writing user gesture bindings to user_preferences."""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.user_preference import UserPreference

PREFERENCE_TYPE = "gesture_bindings"


def get_bindings_for_user(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> List[dict]:
    row = (
        db.query(UserPreference)
        .filter(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.preference_type == PREFERENCE_TYPE,
        )
        .first()
    )
    if not row or not row.value_json:
        return []
    return row.value_json.get("bindings", [])


def get_bindings_metadata(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[datetime]:
    row = (
        db.query(UserPreference)
        .filter(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.preference_type == PREFERENCE_TYPE,
        )
        .first()
    )
    return row.updated_at if row else None


def save_bindings_for_user(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    bindings: List[dict],
) -> None:
    row = (
        db.query(UserPreference)
        .filter(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.preference_type == PREFERENCE_TYPE,
        )
        .first()
    )
    payload = {"bindings": bindings}
    if row:
        row.value_json = payload
        row.updated_at = datetime.utcnow()
        row.evidence_count = (row.evidence_count or 0) + 1
    else:
        row = UserPreference(
            tenant_id=tenant_id,
            user_id=user_id,
            preference_type=PREFERENCE_TYPE,
            value=None,
            value_json=payload,
            confidence=1.0,
            evidence_count=1,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    db.flush()
```

- [ ] **Step 4: Run test → PASS**

```bash
pytest tests/test_gesture_bindings.py::test_service_round_trip -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/gesture_bindings_service.py apps/api/tests/test_gesture_bindings.py
git commit -m "feat(api): gesture_bindings_service with round-trip persistence to user_preferences"
```

---

## Task 1.4: API endpoints `/users/me/gesture-bindings`

**Files:**
- Modify: `apps/api/app/api/v1/users.py`

- [ ] **Step 1: Add failing endpoint test**

Append to `apps/api/tests/test_gesture_bindings.py`:

```python
def test_get_bindings_default_empty(client, auth_headers):
    r = client.get("/api/v1/users/me/gesture-bindings", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"bindings": [], "updated_at": None}


def test_put_then_get_bindings(client, auth_headers):
    payload = {
        "bindings": [
            {
                "id": "b1",
                "gesture": {"pose": "open_palm"},
                "action": {"kind": "nav_hud"},
                "scope": "global",
                "enabled": True,
                "user_recorded": False,
            }
        ]
    }
    put = client.put("/api/v1/users/me/gesture-bindings", json=payload, headers=auth_headers)
    assert put.status_code == 204
    got = client.get("/api/v1/users/me/gesture-bindings", headers=auth_headers).json()
    assert len(got["bindings"]) == 1
    assert got["updated_at"] is not None


def test_put_rejects_oversize(client, auth_headers):
    huge = "x" * 70_000
    payload = {
        "bindings": [{
            "id": "b1",
            "gesture": {"pose": "open_palm"},
            "action": {"kind": "mcp_tool", "params": {"blob": huge}},
            "scope": "global",
            "enabled": True,
            "user_recorded": False,
        }]
    }
    r = client.put("/api/v1/users/me/gesture-bindings", json=payload, headers=auth_headers)
    assert r.status_code in (413, 422)
```

- [ ] **Step 2: Verify failure**

```bash
pytest tests/test_gesture_bindings.py -v -k "get_bindings or put_then_get or oversize"
```
Expected: 3 FAILs (404 routes don't exist).

- [ ] **Step 3: Implement endpoints**

Modify `apps/api/app/api/v1/users.py`. Add imports near the top:

```python
import json
from app.api.deps import limiter  # if not already imported; otherwise use the same import auth.py uses
from app.schemas.gesture_binding import BindingsPayload, BindingsResponse
from app.services import gesture_bindings_service
```

(If `deps.limiter` isn't exported, import the limiter from wherever `auth.py` does — `from app.core.rate_limit import limiter` is the typical home; verify by reading `auth.py` first.)

Add at the bottom of `users.py`:

```python
MAX_BINDINGS_BYTES = 65_536


@router.get("/me/gesture-bindings", response_model=BindingsResponse)
@limiter.limit("60/minute")
def get_my_gesture_bindings(
    request: Request,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    bindings = gesture_bindings_service.get_bindings_for_user(
        db, current_user.tenant_id, current_user.id
    )
    updated_at = gesture_bindings_service.get_bindings_metadata(
        db, current_user.tenant_id, current_user.id
    )
    return BindingsResponse(
        bindings=bindings,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


@router.put("/me/gesture-bindings", status_code=204)
@limiter.limit("10/minute")
def put_my_gesture_bindings(
    request: Request,
    payload: BindingsPayload,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    serialized = payload.model_dump(mode="json")
    if len(json.dumps(serialized)) > MAX_BINDINGS_BYTES:
        raise HTTPException(status_code=413, detail="bindings payload exceeds 64KB cap")
    gesture_bindings_service.save_bindings_for_user(
        db, current_user.tenant_id, current_user.id,
        [b.model_dump(mode="json") for b in payload.bindings],
    )
    db.commit()
    return None
```

Add `Request` to the FastAPI imports at the top.

- [ ] **Step 4: Run all binding tests**

```bash
pytest tests/test_gesture_bindings.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run the full API test suite to catch regressions**

```bash
pytest -x -q
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/api/v1/users.py apps/api/tests/test_gesture_bindings.py
git commit -m "feat(api): GET/PUT /users/me/gesture-bindings with slowapi limits + 64KB cap"
```

---

## Task 1.5: Add `gesture_action` to RL DECISION_POINTS

**Files:**
- Modify: `apps/api/app/services/rl_experience_service.py`

- [ ] **Step 1: Read the existing constant**

```bash
grep -n "DECISION_POINTS\|chat_response\|code_task" apps/api/app/services/rl_experience_service.py | head -10
```

- [ ] **Step 2: Add `'gesture_action'` to the list**

Edit the constant to include `'gesture_action'` between `'agent_routing'` and the closing bracket. Preserve alphabetic order if the existing list is alphabetic; otherwise append.

- [ ] **Step 3: Sanity check via import**

```bash
cd apps/api && python -c "from app.services import rl_experience_service; print('gesture_action' in rl_experience_service.DECISION_POINTS)"
```
Expected: `True`.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/services/rl_experience_service.py
git commit -m "feat(rl): add gesture_action decision point"
```

---

## Task 1.6: Rust gesture module scaffold + types

**Files:**
- Create: `apps/luna-client/src-tauri/src/gesture/mod.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/types.rs`
- Modify: `apps/luna-client/src-tauri/src/lib.rs` (add `mod gesture;`)
- Modify: `apps/luna-client/src-tauri/Cargo.toml` (add deps)

- [ ] **Step 1: Add Cargo dependencies**

In `apps/luna-client/src-tauri/Cargo.toml`, append under `[dependencies]`:

```toml
nokhwa = { version = "0.10", features = ["input-avfoundation"] }
image = "0.24"
futures = "0.3"
tokio = { version = "1", features = ["sync", "time", "rt-multi-thread", "macros"] }
once_cell = "1"
ulid = "1"
```

(`enigo` and `swift-bridge` come in later tasks to keep this commit small.)

- [ ] **Step 2: Create `types.rs` with the GestureEvent + supporting structs**

Create `apps/luna-client/src-tauri/src/gesture/types.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Pose {
    OpenPalm, Fist, Point, Peace, Three, Four, Five, ThumbUp, PinchPose, RotationPose, Custom,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Hand { Left, Right }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MotionKind { Swipe, Pinch, Rotate, Tap, None }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Direction { Up, Down, Left, Right, In, Out, Cw, Ccw }

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct FingersExtended {
    pub thumb: bool, pub index: bool, pub middle: bool, pub ring: bool, pub pinky: bool,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Motion {
    pub kind: MotionKind,
    pub direction: Option<Direction>,
    pub magnitude: f32,
    pub velocity: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GestureEvent {
    pub id: String,
    pub ts: i64,
    pub pose: Pose,
    pub fingers_extended: FingersExtended,
    pub motion: Option<Motion>,
    pub hand: Hand,
    pub confidence: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WakeState { Sleeping, Arming, Armed, Fatal }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineStatus {
    pub state: String,
    pub fps: f32,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, Copy)]
pub struct Landmark { pub x: f32, pub y: f32, pub z: f32 }

#[derive(Debug, Clone)]
pub struct HandFrame {
    pub handedness: Hand,
    pub landmarks: [Landmark; 21],
    pub confidence: f32,
}
```

- [ ] **Step 3: Create `gesture/mod.rs`**

```rust
//! Luna gesture engine — in-process Rust module.
//!
//! Owns webcam capture and hand-landmark recognition; emits GestureEvent
//! over Tauri events to the React frontend.

pub mod types;
pub mod camera;
pub mod landmark;
pub mod pose;
pub mod motion;
pub mod wake;
pub mod recognizer;
pub mod supervisor;

#[cfg(test)]
mod tests;

pub use supervisor::{start_engine, stop_engine, pause_engine, resume_engine, engine_status, list_cameras, set_camera_index};
pub use types::{GestureEvent, EngineStatus, WakeState};
```

- [ ] **Step 4: Wire `mod gesture;` into `lib.rs`**

Add `mod gesture;` near the top of `apps/luna-client/src-tauri/src/lib.rs` (after the existing `use tauri::Manager;` line). Don't register commands yet — those come in Task 1.13.

- [ ] **Step 5: Create empty stubs for the other modules so the crate compiles**

Each of `camera.rs, landmark.rs, pose.rs, motion.rs, wake.rs, recognizer.rs, supervisor.rs` gets a minimal stub:

```rust
//! TODO: implemented in subsequent tasks
```

For `supervisor.rs`, add stub functions matching the re-exports:

```rust
use crate::gesture::types::EngineStatus;

pub async fn start_engine() -> Result<(), String> { Ok(()) }
pub async fn stop_engine() -> Result<(), String> { Ok(()) }
pub async fn pause_engine() -> Result<(), String> { Ok(()) }
pub async fn resume_engine() -> Result<(), String> { Ok(()) }
pub async fn engine_status() -> EngineStatus {
    EngineStatus { state: "stub".into(), fps: 0.0, last_error: None }
}
pub async fn list_cameras() -> Vec<String> { vec![] }
pub async fn set_camera_index(_i: usize) -> Result<(), String> { Ok(()) }
```

- [ ] **Step 6: Push branch to trigger CI build**

(Per global instructions — never run `cargo build` locally.)

```bash
git add apps/luna-client/src-tauri/Cargo.toml apps/luna-client/src-tauri/src/gesture/ apps/luna-client/src-tauri/src/lib.rs
git commit -m "feat(luna): scaffold gesture engine module + types"
git push origin feat/luna-gesture-system
```

Wait for CI. Check status:

```bash
gh run list --branch feat/luna-gesture-system --limit 3
```

If the build fails on a dep, fix and re-push. Do not proceed to 1.7 until the scaffold compiles in CI.

---

## Task 1.7: Pose classifier (geometric, pure-function)

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/pose.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/tests/mod.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/tests/pose_test.rs`

- [ ] **Step 1: Write the failing tests first**

`tests/mod.rs`:
```rust
mod pose_test;
```

`tests/pose_test.rs`:
```rust
use crate::gesture::pose::classify;
use crate::gesture::types::*;

fn lm(x: f32, y: f32, z: f32) -> Landmark { Landmark { x, y, z } }

fn open_palm_landmarks() -> [Landmark; 21] {
    // Stylized: fingers extended away from the wrist (landmark 0 at origin).
    // Indices follow MediaPipe Hands convention.
    let mut a = [lm(0.0, 0.0, 0.0); 21];
    // Thumb chain (1..=4)
    a[1] = lm(-0.05, 0.05, 0.0); a[2] = lm(-0.10, 0.10, 0.0);
    a[3] = lm(-0.13, 0.14, 0.0); a[4] = lm(-0.17, 0.18, 0.0);
    // Index (5..=8)
    a[5] = lm(0.02, 0.10, 0.0); a[6] = lm(0.02, 0.18, 0.0);
    a[7] = lm(0.02, 0.24, 0.0); a[8] = lm(0.02, 0.30, 0.0);
    // Middle (9..=12)
    a[9] = lm(0.04, 0.10, 0.0); a[10] = lm(0.04, 0.20, 0.0);
    a[11] = lm(0.04, 0.27, 0.0); a[12] = lm(0.04, 0.32, 0.0);
    // Ring (13..=16)
    a[13] = lm(0.06, 0.10, 0.0); a[14] = lm(0.06, 0.18, 0.0);
    a[15] = lm(0.06, 0.24, 0.0); a[16] = lm(0.06, 0.30, 0.0);
    // Pinky (17..=20)
    a[17] = lm(0.08, 0.10, 0.0); a[18] = lm(0.08, 0.16, 0.0);
    a[19] = lm(0.08, 0.20, 0.0); a[20] = lm(0.08, 0.24, 0.0);
    a
}

fn fist_landmarks() -> [Landmark; 21] {
    // All tips curled back toward the wrist (within ~0.10 of origin).
    [Landmark { x: 0.02, y: 0.04, z: 0.0 }; 21]
}

#[test]
fn classifies_open_palm() {
    let frame = HandFrame { handedness: Hand::Right, landmarks: open_palm_landmarks(), confidence: 0.9 };
    let (pose, fingers) = classify(&frame);
    assert_eq!(pose, Pose::OpenPalm);
    assert!(fingers.thumb && fingers.index && fingers.middle && fingers.ring && fingers.pinky);
}

#[test]
fn classifies_fist() {
    let frame = HandFrame { handedness: Hand::Right, landmarks: fist_landmarks(), confidence: 0.9 };
    let (pose, fingers) = classify(&frame);
    assert_eq!(pose, Pose::Fist);
}
```

- [ ] **Step 2: Run tests → FAIL**

(Skip locally — CI runs them. Push after step 3.)

- [ ] **Step 3: Implement `pose.rs`**

```rust
use crate::gesture::types::*;

const TIP_INDICES: [usize; 5] = [4, 8, 12, 16, 20];   // thumb, index, middle, ring, pinky tips
const PIP_INDICES: [usize; 5] = [3, 6, 10, 14, 18];   // adjacent PIP joints
const WRIST: usize = 0;

fn dist(a: Landmark, b: Landmark) -> f32 {
    let dx = a.x - b.x; let dy = a.y - b.y; let dz = a.z - b.z;
    (dx * dx + dy * dy + dz * dz).sqrt()
}

fn finger_extended(lm: &[Landmark; 21], tip_idx: usize, pip_idx: usize) -> bool {
    dist(lm[tip_idx], lm[WRIST]) > dist(lm[pip_idx], lm[WRIST])
}

pub fn classify(frame: &HandFrame) -> (Pose, FingersExtended) {
    let lm = &frame.landmarks;
    let extended: [bool; 5] = std::array::from_fn(|i| finger_extended(lm, TIP_INDICES[i], PIP_INDICES[i]));
    let fingers = FingersExtended {
        thumb: extended[0], index: extended[1], middle: extended[2], ring: extended[3], pinky: extended[4],
    };
    let count_non_thumb = extended[1..].iter().filter(|b| **b).count();
    let pose = match (extended[0], count_non_thumb) {
        (_, 0) => Pose::Fist,
        (true, 4) => Pose::OpenPalm,
        (false, 4) => Pose::Four,
        (true, 1) if extended[1] => Pose::Point,        // fallthrough below
        (false, 1) if extended[1] => Pose::Point,
        (false, 2) if extended[1] && extended[2] => Pose::Peace,
        (false, 3) if extended[1] && extended[2] && extended[3] => Pose::Three,
        (true, 4) => Pose::Five,                          // covered above; defensive
        (true, 0) => Pose::ThumbUp,
        _ => Pose::Custom,
    };
    (pose, fingers)
}
```

- [ ] **Step 4: Push, wait for CI tests**

```bash
git add apps/luna-client/src-tauri/src/gesture/pose.rs apps/luna-client/src-tauri/src/gesture/tests/
git commit -m "feat(luna): geometric pose classifier with unit tests"
git push
```

Watch CI:

```bash
gh run watch
```

Expected: all unit tests pass.

---

## Task 1.8: Motion analyzer (ring buffer)

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/motion.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/tests/motion_test.rs`

- [ ] **Step 1: Write failing tests for swipe/pinch/tap**

`tests/motion_test.rs`:

```rust
use crate::gesture::motion::MotionAnalyzer;
use crate::gesture::types::*;

fn lm(x: f32, y: f32) -> Landmark { Landmark { x, y, z: 0.0 } }

fn frame_at(palm_x: f32, palm_y: f32) -> HandFrame {
    let mut a = [lm(0.0, 0.0); 21];
    // index 9 = palm-center proxy in MediaPipe
    a[9] = lm(palm_x, palm_y);
    HandFrame { handedness: Hand::Right, landmarks: a, confidence: 0.9 }
}

#[test]
fn detects_swipe_right() {
    let mut a = MotionAnalyzer::new();
    for i in 0..10 {
        a.push(&frame_at(i as f32 * 0.05, 0.5), 1700_000_000_000 + i * 33);
    }
    let m = a.classify().expect("motion should be classified");
    assert_eq!(m.kind, MotionKind::Swipe);
    assert_eq!(m.direction, Some(Direction::Right));
}

#[test]
fn idle_returns_none_kind() {
    let mut a = MotionAnalyzer::new();
    for i in 0..10 {
        a.push(&frame_at(0.5, 0.5), 1700_000_000_000 + i * 33);
    }
    let m = a.classify().unwrap_or(Motion {
        kind: MotionKind::None, direction: None, magnitude: 0.0, velocity: 0.0,
    });
    assert_eq!(m.kind, MotionKind::None);
}
```

Add `mod motion_test;` to `gesture/tests/mod.rs`.

- [ ] **Step 2: Implement `motion.rs`**

```rust
use std::collections::VecDeque;
use crate::gesture::types::*;

const WINDOW: usize = 30;
const SWIPE_MIN_MAGNITUDE: f32 = 0.20;
const SWIPE_MAX_DURATION_MS: i64 = 350;

pub struct MotionAnalyzer {
    samples: VecDeque<(Landmark, i64)>,
}

impl MotionAnalyzer {
    pub fn new() -> Self { Self { samples: VecDeque::with_capacity(WINDOW) } }

    pub fn push(&mut self, frame: &HandFrame, ts_ms: i64) {
        if self.samples.len() == WINDOW { self.samples.pop_front(); }
        self.samples.push_back((frame.landmarks[9], ts_ms));
    }

    pub fn classify(&self) -> Option<Motion> {
        if self.samples.len() < 5 { return None; }
        let (start, t0) = *self.samples.front()?;
        let (end, t1) = *self.samples.back()?;
        let dx = end.x - start.x;
        let dy = end.y - start.y;
        let mag = (dx * dx + dy * dy).sqrt();
        let dur = t1 - t0;
        if mag >= SWIPE_MIN_MAGNITUDE && dur > 0 && dur <= SWIPE_MAX_DURATION_MS {
            let dir = if dx.abs() > dy.abs() {
                if dx > 0.0 { Direction::Right } else { Direction::Left }
            } else if dy > 0.0 { Direction::Down } else { Direction::Up };
            return Some(Motion {
                kind: MotionKind::Swipe,
                direction: Some(dir),
                magnitude: mag.min(1.0),
                velocity: mag / (dur as f32 / 1000.0),
            });
        }
        Some(Motion { kind: MotionKind::None, direction: None, magnitude: 0.0, velocity: 0.0 })
    }

    pub fn clear(&mut self) { self.samples.clear(); }
}
```

(Pinch/rotate/tap are stubbed in v1 — added in Phase 3 with the spike's chosen runtime, since they need higher-resolution landmark deltas.)

- [ ] **Step 3: Push and verify CI green**

```bash
git add apps/luna-client/src-tauri/src/gesture/motion.rs apps/luna-client/src-tauri/src/gesture/tests/
git commit -m "feat(luna): motion analyzer with swipe detection + tests"
git push && gh run watch
```

---

## Task 1.9: Wake-state machine

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/wake.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/tests/wake_test.rs`

- [ ] **Step 1: Write failing tests covering all transitions**

`tests/wake_test.rs`:

```rust
use crate::gesture::wake::{WakeMachine, WakeInput};
use crate::gesture::types::{Pose, WakeState};

#[test]
fn sleeps_initially() {
    let m = WakeMachine::new();
    assert_eq!(m.state(), WakeState::Sleeping);
}

#[test]
fn open_palm_500ms_arms() {
    let mut m = WakeMachine::new();
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 0);
    assert_eq!(m.state(), WakeState::Arming);
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 600);
    assert_eq!(m.state(), WakeState::Armed);
}

#[test]
fn pose_change_during_arming_returns_to_sleeping() {
    let mut m = WakeMachine::new();
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 0);
    m.tick(WakeInput::Pose { pose: Some(Pose::Fist), confidence: 0.9 }, 200);
    assert_eq!(m.state(), WakeState::Sleeping);
}

#[test]
fn idle_5s_disarms() {
    let mut m = WakeMachine::new();
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 0);
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 600);
    assert_eq!(m.state(), WakeState::Armed);
    m.tick(WakeInput::Idle, 6000);
    assert_eq!(m.state(), WakeState::Sleeping);
}

#[test]
fn confirm_pending_freezes_idle_timer() {
    let mut m = WakeMachine::new();
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 0);
    m.tick(WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence: 0.9 }, 600);
    m.set_confirm_pending(true);
    m.tick(WakeInput::Idle, 7000);   // would normally disarm
    assert_eq!(m.state(), WakeState::Armed);
    m.set_confirm_pending(false);
    m.tick(WakeInput::Idle, 13000);  // 6s after confirm cleared
    assert_eq!(m.state(), WakeState::Sleeping);
}
```

Register `mod wake_test;` in `tests/mod.rs`.

- [ ] **Step 2: Implement `wake.rs`**

```rust
use crate::gesture::types::{Pose, WakeState};

const ARM_HOLD_MS: i64 = 500;
const IDLE_TIMEOUT_MS: i64 = 5000;
const ARM_CONFIDENCE: f32 = 0.85;

pub enum WakeInput {
    Pose { pose: Option<Pose>, confidence: f32 },
    Idle,
}

pub struct WakeMachine {
    state: WakeState,
    arming_started_at: Option<i64>,
    last_activity_ms: i64,
    confirm_pending: bool,
}

impl WakeMachine {
    pub fn new() -> Self {
        Self { state: WakeState::Sleeping, arming_started_at: None, last_activity_ms: 0, confirm_pending: false }
    }

    pub fn state(&self) -> WakeState { self.state }

    pub fn set_confirm_pending(&mut self, v: bool) { self.confirm_pending = v; }

    pub fn tick(&mut self, input: WakeInput, now_ms: i64) {
        match (&self.state, input) {
            (WakeState::Sleeping, WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence })
                if confidence >= ARM_CONFIDENCE => {
                self.state = WakeState::Arming;
                self.arming_started_at = Some(now_ms);
            }
            (WakeState::Arming, WakeInput::Pose { pose: Some(Pose::OpenPalm), confidence })
                if confidence >= ARM_CONFIDENCE => {
                if let Some(start) = self.arming_started_at {
                    if now_ms - start >= ARM_HOLD_MS {
                        self.state = WakeState::Armed;
                        self.last_activity_ms = now_ms;
                        self.arming_started_at = None;
                    }
                }
            }
            (WakeState::Arming, WakeInput::Pose { .. }) => {
                self.state = WakeState::Sleeping;
                self.arming_started_at = None;
            }
            (WakeState::Armed, WakeInput::Pose { .. }) => {
                self.last_activity_ms = now_ms;
            }
            (WakeState::Armed, WakeInput::Idle) if !self.confirm_pending => {
                if now_ms - self.last_activity_ms >= IDLE_TIMEOUT_MS {
                    self.state = WakeState::Sleeping;
                }
            }
            _ => {}
        }
    }
}
```

- [ ] **Step 3: Push, watch CI**

```bash
git add apps/luna-client/src-tauri/src/gesture/wake.rs apps/luna-client/src-tauri/src/gesture/tests/
git commit -m "feat(luna): wake state machine with arming, idle disarm, confirm-pending freeze"
git push && gh run watch
```

---

## Task 1.10: Camera capture (`camera.rs`) via nokhwa

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/camera.rs`

(No unit tests — camera is an integration concern; smoke-tested via end-to-end at Task 1.16.)

- [ ] **Step 1: Implement `camera.rs`**

```rust
use nokhwa::{Camera, utils::{CameraIndex, RequestedFormat, RequestedFormatType, Resolution, FrameFormat}};
use nokhwa::pixel_format::RgbFormat;
use tokio::sync::mpsc;
use tokio::task;
use crate::gesture::types::*;

#[derive(Clone)]
pub struct Frame {
    pub width: u32,
    pub height: u32,
    pub rgb: Vec<u8>,
    pub ts_ms: i64,
}

#[derive(Debug, Clone)]
pub enum CameraEvent {
    Frame(Frame),
    Disconnected,
    Error(String),
}

pub struct CameraStream {
    pub rx: mpsc::Receiver<CameraEvent>,
    pub stop_tx: mpsc::Sender<()>,
}

pub fn list_devices() -> Vec<(usize, String)> {
    nokhwa::query(nokhwa::utils::ApiBackend::AVFoundation)
        .unwrap_or_default()
        .into_iter()
        .map(|info| (info.index().as_index().unwrap_or(0) as usize, info.human_name()))
        .collect()
}

pub fn start(index: usize, fps_target: u32) -> Result<CameraStream, String> {
    let (tx, rx) = mpsc::channel::<CameraEvent>(8);
    let (stop_tx, mut stop_rx) = mpsc::channel::<()>(1);

    task::spawn_blocking(move || {
        let format = RequestedFormat::new::<RgbFormat>(
            RequestedFormatType::AbsoluteHighestFrameRate,
        );
        let mut camera = match Camera::new(CameraIndex::Index(index as u32), format) {
            Ok(c) => c,
            Err(e) => { let _ = tx.blocking_send(CameraEvent::Error(format!("camera init: {e}"))); return; }
        };
        if let Err(e) = camera.open_stream() {
            let _ = tx.blocking_send(CameraEvent::Error(format!("open_stream: {e}")));
            return;
        }
        let frame_dur = std::time::Duration::from_millis((1000 / fps_target.max(1)) as u64);
        loop {
            if stop_rx.try_recv().is_ok() { break; }
            match camera.frame() {
                Ok(buf) => {
                    let img = match buf.decode_image::<RgbFormat>() {
                        Ok(i) => i,
                        Err(e) => { let _ = tx.blocking_send(CameraEvent::Error(format!("decode: {e}"))); continue; }
                    };
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis() as i64;
                    let frame = Frame {
                        width: img.width(), height: img.height(), rgb: img.into_raw(), ts_ms: now_ms,
                    };
                    if tx.blocking_send(CameraEvent::Frame(frame)).is_err() { break; }
                }
                Err(e) => { let _ = tx.blocking_send(CameraEvent::Error(format!("frame: {e}"))); }
            }
            std::thread::sleep(frame_dur);
        }
        let _ = camera.stop_stream();
    });

    Ok(CameraStream { rx, stop_tx })
}
```

- [ ] **Step 2: Push, verify CI compiles**

```bash
git add apps/luna-client/src-tauri/src/gesture/camera.rs
git commit -m "feat(luna): nokhwa-based camera capture with stop signal + hot-plug error events"
git push && gh run watch
```

---

## Task 1.11: Landmark spike — Apple Vision FFI

**Files:**
- Create: `apps/luna-client/src-tauri/swift/HandLandmarker.swift`
- Modify: `apps/luna-client/src-tauri/Cargo.toml` (add `swift-bridge` build dep)
- Modify: `apps/luna-client/src-tauri/build.rs`
- Modify: `apps/luna-client/src-tauri/src/gesture/landmark.rs`
- Create: `apps/luna-client/src-tauri/src/gesture/landmark_apple_vision.rs`

This is the spike. **Time-box: 2 days.** If the Swift FFI proves intractable, fall back to MediaPipe Tasks C++ (next task plan revision will pivot — flag and stop here).

- [ ] **Step 1: Add `swift-bridge` build deps**

`Cargo.toml`:

```toml
[build-dependencies]
tauri-build = { version = "2", features = [] }
swift-bridge-build = "0.1"

[dependencies]
swift-bridge = "0.1"
```

- [ ] **Step 2: Write the Swift helper**

`apps/luna-client/src-tauri/swift/HandLandmarker.swift`:

```swift
import Foundation
import Vision
import CoreImage
import VideoToolbox

@_cdecl("luna_extract_landmarks")
public func luna_extract_landmarks(
    rgbBytes: UnsafePointer<UInt8>,
    width: Int32,
    height: Int32,
    outBuf: UnsafeMutablePointer<Float>,   // 2 hands × 21 landmarks × 3 floats = 126 floats
    outConfidence: UnsafeMutablePointer<Float>,  // 2 confidences
    outHandednessLeft: UnsafeMutablePointer<UInt8>  // 2 bytes (0=right, 1=left)
) -> Int32 {
    let bufferSize = Int(width) * Int(height) * 3
    let data = Data(bytes: rgbBytes, count: bufferSize)
    let ciImage = CIImage(bitmapData: data,
                          bytesPerRow: Int(width) * 3,
                          size: CGSize(width: Int(width), height: Int(height)),
                          format: .RGB8,
                          colorSpace: CGColorSpaceCreateDeviceRGB())
    let context = CIContext()
    guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return 0 }

    let request = VNDetectHumanHandPoseRequest()
    request.maximumHandCount = 2

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do { try handler.perform([request]) } catch { return 0 }

    guard let observations = request.results else { return 0 }
    var handsWritten: Int32 = 0
    for (idx, obs) in observations.prefix(2).enumerated() {
        guard let allPoints = try? obs.recognizedPoints(.all) else { continue }
        // Map Vision joint names to MediaPipe-style 21-landmark layout
        let order: [VNHumanHandPoseObservation.JointName] = [
            .wrist,
            .thumbCMC, .thumbMP, .thumbIP, .thumbTip,
            .indexMCP, .indexPIP, .indexDIP, .indexTip,
            .middleMCP, .middlePIP, .middleDIP, .middleTip,
            .ringMCP, .ringPIP, .ringDIP, .ringTip,
            .littleMCP, .littlePIP, .littleDIP, .littleTip,
        ]
        for (i, joint) in order.enumerated() {
            if let p = allPoints[joint], p.confidence > 0.3 {
                outBuf[(idx * 21 + i) * 3 + 0] = Float(p.location.x)
                outBuf[(idx * 21 + i) * 3 + 1] = Float(1.0 - p.location.y)  // flip y to image space
                outBuf[(idx * 21 + i) * 3 + 2] = 0.0
            } else {
                outBuf[(idx * 21 + i) * 3 + 0] = 0
                outBuf[(idx * 21 + i) * 3 + 1] = 0
                outBuf[(idx * 21 + i) * 3 + 2] = 0
            }
        }
        outConfidence[idx] = obs.confidence
        outHandednessLeft[idx] = (obs.chirality == .left) ? 1 : 0
        handsWritten += 1
    }
    return handsWritten
}
```

- [ ] **Step 3: Update `build.rs` to compile and link the Swift code**

```rust
fn main() {
    // Existing tauri-build call
    tauri_build::build();

    // Compile the Swift helper into a static library and link it
    #[cfg(target_os = "macos")]
    {
        let swift_src = "swift/HandLandmarker.swift";
        let out_dir = std::env::var("OUT_DIR").unwrap();
        let lib_path = format!("{}/libluna_hand_landmarker.a", out_dir);
        let status = std::process::Command::new("swiftc")
            .args([
                "-emit-library",
                "-static",
                "-o", &lib_path,
                "-target", "arm64-apple-macos11",
                "-parse-as-library",
                swift_src,
            ])
            .status()
            .expect("failed to invoke swiftc");
        assert!(status.success(), "swiftc failed");
        println!("cargo:rustc-link-search=native={}", out_dir);
        println!("cargo:rustc-link-lib=static=luna_hand_landmarker");
        println!("cargo:rustc-link-lib=framework=Vision");
        println!("cargo:rustc-link-lib=framework=CoreImage");
        println!("cargo:rerun-if-changed=swift/HandLandmarker.swift");
    }
}
```

- [ ] **Step 4: Implement Rust-side wrapper**

`landmark.rs`:

```rust
use crate::gesture::types::*;

pub trait LandmarkExtractor: Send + Sync {
    fn extract(&self, rgb: &[u8], width: u32, height: u32) -> Vec<HandFrame>;
}

#[cfg(target_os = "macos")]
pub use crate::gesture::landmark_apple_vision::AppleVisionExtractor;
```

`landmark_apple_vision.rs`:

```rust
use crate::gesture::types::*;
use crate::gesture::landmark::LandmarkExtractor;

extern "C" {
    fn luna_extract_landmarks(
        rgb_bytes: *const u8, width: i32, height: i32,
        out_buf: *mut f32, out_conf: *mut f32, out_left: *mut u8,
    ) -> i32;
}

pub struct AppleVisionExtractor;

impl LandmarkExtractor for AppleVisionExtractor {
    fn extract(&self, rgb: &[u8], width: u32, height: u32) -> Vec<HandFrame> {
        let mut buf = [0f32; 126];
        let mut conf = [0f32; 2];
        let mut left = [0u8; 2];
        let n = unsafe {
            luna_extract_landmarks(
                rgb.as_ptr(), width as i32, height as i32,
                buf.as_mut_ptr(), conf.as_mut_ptr(), left.as_mut_ptr(),
            )
        };
        (0..n as usize).map(|h| {
            let mut lm = [Landmark { x: 0.0, y: 0.0, z: 0.0 }; 21];
            for i in 0..21 {
                lm[i] = Landmark {
                    x: buf[(h * 21 + i) * 3 + 0],
                    y: buf[(h * 21 + i) * 3 + 1],
                    z: buf[(h * 21 + i) * 3 + 2],
                };
            }
            HandFrame {
                handedness: if left[h] == 1 { Hand::Left } else { Hand::Right },
                landmarks: lm,
                confidence: conf[h],
            }
        }).collect()
    }
}
```

- [ ] **Step 5: Push and verify CI builds the Swift static lib + Rust wrapper**

```bash
git add apps/luna-client/src-tauri/Cargo.toml apps/luna-client/src-tauri/build.rs apps/luna-client/src-tauri/swift/ apps/luna-client/src-tauri/src/gesture/landmark.rs apps/luna-client/src-tauri/src/gesture/landmark_apple_vision.rs
git commit -m "feat(luna): Apple Vision hand landmarker via Swift FFI (spike)"
git push && gh run watch
```

If CI fails on swiftc invocation: ensure the GitHub-hosted runner supports macOS 14+ Vision symbols. If not, escalate; do not silently fall back.

---

## Task 1.12: Recognizer + supervisor (engine main loop)

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/recognizer.rs`
- Modify: `apps/luna-client/src-tauri/src/gesture/supervisor.rs`

- [ ] **Step 1: Implement `recognizer.rs`**

```rust
use ulid::Ulid;
use crate::gesture::types::*;
use crate::gesture::pose::classify;
use crate::gesture::motion::MotionAnalyzer;

const DEBOUNCE_MS: i64 = 80;

pub struct Recognizer {
    motion: MotionAnalyzer,
    last_emit_ms: i64,
}

impl Recognizer {
    pub fn new() -> Self { Self { motion: MotionAnalyzer::new(), last_emit_ms: 0 } }

    pub fn ingest(&mut self, hands: Vec<HandFrame>, now_ms: i64) -> (Option<GestureEvent>, Option<Pose>) {
        let primary = match hands.first() { Some(h) => h, None => return (None, None) };
        let (pose, fingers) = classify(primary);
        self.motion.push(primary, now_ms);

        if now_ms - self.last_emit_ms < DEBOUNCE_MS {
            return (None, Some(pose));
        }

        let motion = self.motion.classify();
        let event = GestureEvent {
            id: Ulid::new().to_string(),
            ts: now_ms,
            pose,
            fingers_extended: fingers,
            motion,
            hand: primary.handedness,
            confidence: primary.confidence,
        };
        self.last_emit_ms = now_ms;
        (Some(event), Some(pose))
    }
}
```

- [ ] **Step 2: Implement `supervisor.rs`** (engine task lifecycle)

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio::time::Duration;
use once_cell::sync::Lazy;

use tauri::{AppHandle, Emitter};

use crate::gesture::camera::{self, CameraEvent};
use crate::gesture::landmark::AppleVisionExtractor;
use crate::gesture::landmark::LandmarkExtractor;
use crate::gesture::recognizer::Recognizer;
use crate::gesture::wake::{WakeInput, WakeMachine};
use crate::gesture::types::*;

static RUNNING: AtomicBool = AtomicBool::new(false);
static PAUSED: AtomicBool = AtomicBool::new(false);
static CAMERA_INDEX: AtomicUsize = AtomicUsize::new(0);

static HANDLE: Lazy<Mutex<Option<JoinHandle<()>>>> = Lazy::new(|| Mutex::new(None));
static APP_HANDLE: Lazy<Mutex<Option<AppHandle>>> = Lazy::new(|| Mutex::new(None));

const MAX_RESTARTS: usize = 3;

pub async fn install_app_handle(handle: AppHandle) {
    *APP_HANDLE.lock().await = Some(handle);
}

pub async fn list_cameras() -> Vec<String> {
    camera::list_devices().into_iter().map(|(_, name)| name).collect()
}

pub async fn set_camera_index(i: usize) -> Result<(), String> {
    CAMERA_INDEX.store(i, Ordering::SeqCst);
    Ok(())
}

pub async fn engine_status() -> EngineStatus {
    EngineStatus {
        state: if PAUSED.load(Ordering::SeqCst) { "paused".into() }
               else if RUNNING.load(Ordering::SeqCst) { "running".into() }
               else { "stopped".into() },
        fps: 0.0,
        last_error: None,
    }
}

pub async fn pause_engine() -> Result<(), String> {
    PAUSED.store(true, Ordering::SeqCst);
    stop_engine().await
}

pub async fn resume_engine() -> Result<(), String> {
    PAUSED.store(false, Ordering::SeqCst);
    start_engine().await
}

pub async fn start_engine() -> Result<(), String> {
    if RUNNING.swap(true, Ordering::SeqCst) {
        return Ok(()); // already running
    }
    let app = APP_HANDLE.lock().await.clone()
        .ok_or_else(|| "app handle not installed".to_string())?;

    let h = tokio::spawn(async move {
        let mut restarts = 0;
        while RUNNING.load(Ordering::SeqCst) && restarts <= MAX_RESTARTS {
            let result = run_engine_loop(app.clone()).await;
            if let Err(e) = result {
                let _ = app.emit("engine-status", EngineStatus {
                    state: "error".into(), fps: 0.0, last_error: Some(e.clone()),
                });
                restarts += 1;
                tokio::time::sleep(Duration::from_millis(500)).await;
                continue;
            }
            break;
        }
        if restarts > MAX_RESTARTS {
            let _ = app.emit("engine-status", EngineStatus {
                state: "fatal".into(), fps: 0.0,
                last_error: Some("restart budget exhausted".into()),
            });
            RUNNING.store(false, Ordering::SeqCst);
        }
    });

    *HANDLE.lock().await = Some(h);
    Ok(())
}

pub async fn stop_engine() -> Result<(), String> {
    RUNNING.store(false, Ordering::SeqCst);
    if let Some(h) = HANDLE.lock().await.take() { h.abort(); }
    Ok(())
}

async fn run_engine_loop(app: AppHandle) -> Result<(), String> {
    let extractor = AppleVisionExtractor;
    let mut wake = WakeMachine::new();
    let mut recog = Recognizer::new();

    let mut last_state = WakeState::Sleeping;
    let mut stream = camera::start(CAMERA_INDEX.load(Ordering::SeqCst), 30)?;

    while RUNNING.load(Ordering::SeqCst) {
        let evt = match stream.rx.recv().await {
            Some(e) => e, None => break,
        };
        let now_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis() as i64;
        match evt {
            CameraEvent::Frame(frame) => {
                let _ = app.emit("spatial-frame", &frame.ts_ms); // existing HUD consumer
                let hands = extractor.extract(&frame.rgb, frame.width, frame.height);
                let primary_pose = hands.first().map(|h| {
                    crate::gesture::pose::classify(h).0
                });
                wake.tick(WakeInput::Pose { pose: primary_pose, confidence: hands.first().map(|h| h.confidence).unwrap_or(0.0) }, now_ms);
                if last_state != wake.state() {
                    last_state = wake.state();
                    let _ = app.emit("wake-state-changed", &last_state);
                }
                if matches!(wake.state(), WakeState::Armed) {
                    let (event, _) = recog.ingest(hands, now_ms);
                    if let Some(ev) = event {
                        let _ = app.emit("gesture-event", &ev);
                    }
                } else {
                    wake.tick(WakeInput::Idle, now_ms);
                }
            }
            CameraEvent::Disconnected => return Err("camera disconnected".into()),
            CameraEvent::Error(e) => return Err(e),
        }
    }
    Ok(())
}
```

- [ ] **Step 3: Push, watch CI**

```bash
git add apps/luna-client/src-tauri/src/gesture/recognizer.rs apps/luna-client/src-tauri/src/gesture/supervisor.rs
git commit -m "feat(luna): gesture engine main loop + supervisor with bounded restart"
git push && gh run watch
```

---

## Task 1.13: Tauri commands + tray + global shortcut

**Files:**
- Modify: `apps/luna-client/src-tauri/src/lib.rs`
- Modify: `apps/luna-client/src-tauri/tauri.conf.json`

- [ ] **Step 1: Register Tauri commands**

In `lib.rs`, add the gesture commands and register them in `tauri::generate_handler!`. Example wrapper:

```rust
#[tauri::command]
async fn gesture_start() -> Result<(), String> { gesture::start_engine().await }

#[tauri::command]
async fn gesture_stop() -> Result<(), String> { gesture::stop_engine().await }

#[tauri::command]
async fn gesture_pause() -> Result<(), String> { gesture::pause_engine().await }

#[tauri::command]
async fn gesture_resume() -> Result<(), String> { gesture::resume_engine().await }

#[tauri::command]
async fn gesture_status() -> Result<gesture::EngineStatus, String> { Ok(gesture::engine_status().await) }

#[tauri::command]
async fn gesture_list_cameras() -> Result<Vec<String>, String> { Ok(gesture::list_cameras().await) }

#[tauri::command]
async fn gesture_set_camera_index(i: usize) -> Result<(), String> { gesture::set_camera_index(i).await }
```

In the `setup` closure, capture the AppHandle and install it:

```rust
let h = app.handle().clone();
tauri::async_runtime::spawn(async move {
    crate::gesture::supervisor::install_app_handle(h).await;
    let _ = crate::gesture::supervisor::start_engine().await;
});
```

In `generate_handler!` macro, add the new commands.

- [ ] **Step 2: Add `Cmd+Shift+G` global shortcut**

Find the existing `tauri-plugin-global-shortcut` registration block and add:

```rust
.with_handler(|app, shortcut, _event| {
    if shortcut.matches(Modifiers::SUPER | Modifiers::SHIFT, Code::KeyG) {
        let h = app.clone();
        tauri::async_runtime::spawn(async move {
            // toggle pause
            let status = crate::gesture::supervisor::engine_status().await;
            if status.state == "paused" {
                let _ = crate::gesture::supervisor::resume_engine().await;
            } else {
                let _ = crate::gesture::supervisor::pause_engine().await;
            }
        });
    }
})
```

(Adapt to the actual handler signature in current code — read it first.)

- [ ] **Step 3: Add Info.plist entries**

In `tauri.conf.json`, under `bundle.macOS.entitlements` (or `bundle.macOS.infoPlist`), add:

```json
"NSCameraUsageDescription": "Luna uses your camera to recognize hand gestures.",
"NSAccessibilityUsageDescription": "Luna uses Accessibility access to move the cursor and click via hand gestures."
```

- [ ] **Step 4: Push, watch CI build**

```bash
git add apps/luna-client/src-tauri/src/lib.rs apps/luna-client/src-tauri/tauri.conf.json
git commit -m "feat(luna): register gesture Tauri commands + Cmd+Shift+G killswitch + Info.plist permissions"
git push && gh run watch
```

---

## Task 1.14: Replace `start_spatial_capture` placeholder + delete legacy GestureController

**Files:**
- Modify: `apps/luna-client/src-tauri/src/lib.rs` (remove synthetic `spatial-frame` timer)
- Delete: `apps/luna-client/src/components/spatial/GestureController.jsx`

- [ ] **Step 1: Verify the engine now emits `spatial-frame` events**

Confirm the engine loop in `supervisor.rs::run_engine_loop` already emits `spatial-frame` (it does in Task 1.12 step 2). If not, add the emit.

- [ ] **Step 2: Remove the synthetic timer in `lib.rs`**

Find `start_spatial_capture` in `lib.rs` (around lines 127–164) and replace its body with:

```rust
#[tauri::command]
async fn start_spatial_capture(_app: AppHandle) -> Result<(), String> {
    // Frames are now emitted by the gesture engine; this is a no-op kept for FFI compatibility.
    Ok(())
}
```

Keep `stop_spatial_capture` similarly minimal.

- [ ] **Step 3: Delete the legacy GestureController**

```bash
rm apps/luna-client/src/components/spatial/GestureController.jsx
```

Audit imports:

```bash
grep -rln "GestureController" apps/luna-client/src
```

Expected: empty (any consumers were `SpatialHUD` which we'll re-wire next task).

- [ ] **Step 4: Commit**

```bash
git add -A apps/luna-client/src-tauri/src/lib.rs apps/luna-client/src/components/spatial/
git commit -m "refactor(luna): drop synthetic start_spatial_capture timer; delete legacy GestureController.jsx"
git push && gh run watch
```

---

## Task 1.15: Frontend GestureContext + useGesture + GestureOverlay

**Files:**
- Create: `apps/luna-client/src/context/GestureContext.jsx`
- Create: `apps/luna-client/src/hooks/useGesture.js`
- Create: `apps/luna-client/src/components/gestures/GestureOverlay.jsx`
- Create: `apps/luna-client/src/components/gestures/defaults.js`
- Modify: `apps/luna-client/src/App.jsx`
- Modify: `apps/luna-client/src/components/spatial/KnowledgeNebula.jsx`

- [ ] **Step 1: Add Vitest dev dep + a minimal config (if not already present)**

Check `package.json`:

```bash
grep -E "vitest|@testing-library" apps/luna-client/package.json
```

If missing, add to devDependencies:

```json
"vitest": "^1.6.0",
"@testing-library/react": "^14.0.0",
"@testing-library/jest-dom": "^6.0.0",
"jsdom": "^24.0.0"
```

And add `"test": "vitest run"` to scripts. Commit dev-dep change separately.

- [ ] **Step 2: Write the failing context test**

Create `apps/luna-client/src/components/gestures/__tests__/GestureContext.test.jsx`:

```jsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { GestureProvider } from '../../../context/GestureContext';
import { useGesture } from '../../../hooks/useGesture';

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(async (_name, _cb) => () => {}),
}));

function Probe() {
  const { wakeState } = useGesture();
  return <div data-testid="state">{wakeState}</div>;
}

describe('GestureProvider', () => {
  it('exposes default sleeping state', () => {
    render(<GestureProvider><Probe /></GestureProvider>);
    expect(screen.getByTestId('state').textContent).toBe('sleeping');
  });
});
```

- [ ] **Step 3: Implement `defaults.js`**

```js
// Default bindings — Apple-trackpad-mirrored + Luna extensions.
export const DEFAULT_BINDINGS = [
  { id: 'd-wake', gesture: { pose: 'open_palm' }, action: { kind: 'nav_hud' }, scope: 'global', enabled: false, user_recorded: false },
  { id: 'd-3up',  gesture: { pose: 'three', motion: { kind: 'swipe', direction: 'up' } }, action: { kind: 'nav_hud' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-3dn',  gesture: { pose: 'three', motion: { kind: 'swipe', direction: 'down' } }, action: { kind: 'nav_chat' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-3lt',  gesture: { pose: 'three', motion: { kind: 'swipe', direction: 'left' } }, action: { kind: 'agent_prev' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-3rt',  gesture: { pose: 'three', motion: { kind: 'swipe', direction: 'right' } }, action: { kind: 'agent_next' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-4in',  gesture: { pose: 'four', motion: { kind: 'pinch', direction: 'in' } }, action: { kind: 'nav_command_palette' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-fist', gesture: { pose: 'fist' }, action: { kind: 'dismiss' }, scope: 'global', enabled: true, user_recorded: false },
  { id: 'd-five-grab', gesture: { pose: 'five', motion: { kind: 'tap' } }, action: { kind: 'memory_record' }, scope: 'global', enabled: true, user_recorded: false },
];
```

- [ ] **Step 4: Implement `GestureContext.jsx`**

```jsx
import React, { createContext, useEffect, useMemo, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { DEFAULT_BINDINGS } from '../components/gestures/defaults';

export const GestureContext = createContext(null);

function bindingMatches(binding, event) {
  if (!binding.enabled) return false;
  if (binding.gesture.pose !== event.pose) return false;
  if (binding.gesture.motion) {
    if (!event.motion) return false;
    if (binding.gesture.motion.kind !== event.motion.kind) return false;
    if (binding.gesture.motion.direction && binding.gesture.motion.direction !== event.motion.direction) return false;
  }
  return true;
}

export function GestureProvider({ children, bindings = DEFAULT_BINDINGS, onAction }) {
  const [wakeState, setWakeState] = useState('sleeping');
  const [lastEvent, setLastEvent] = useState(null);
  const [status, setStatus] = useState({ state: 'stopped', fps: 0 });
  const bindingsRef = useRef(bindings);
  bindingsRef.current = bindings;

  useEffect(() => {
    let unsubGesture, unsubWake, unsubStatus;
    (async () => {
      unsubGesture = await listen('gesture-event', (e) => {
        const event = e.payload;
        setLastEvent(event);
        const match = bindingsRef.current.find((b) => bindingMatches(b, event));
        if (match && onAction) onAction(match, event);
      });
      unsubWake = await listen('wake-state-changed', (e) => setWakeState(e.payload));
      unsubStatus = await listen('engine-status', (e) => setStatus(e.payload));
    })().catch(() => {});
    return () => {
      if (unsubGesture) unsubGesture();
      if (unsubWake) unsubWake();
      if (unsubStatus) unsubStatus();
    };
  }, [onAction]);

  const value = useMemo(() => ({ wakeState, lastEvent, status }), [wakeState, lastEvent, status]);
  return <GestureContext.Provider value={value}>{children}</GestureContext.Provider>;
}
```

`useGesture.js`:

```js
import { useContext } from 'react';
import { GestureContext } from '../context/GestureContext';

export function useGesture() {
  const ctx = useContext(GestureContext);
  if (!ctx) return { wakeState: 'sleeping', lastEvent: null, status: { state: 'stopped' } };
  return ctx;
}
```

- [ ] **Step 5: Run the test**

Push and let CI run, or locally if vitest is set up:

```bash
cd apps/luna-client && npx vitest run src/components/gestures/__tests__/GestureContext.test.jsx
```

Expected: PASS.

- [ ] **Step 6: Implement `GestureOverlay.jsx`** (replaces the deleted GestureController behavior)

```jsx
import React from 'react';
import { useGesture } from '../../hooks/useGesture';

export default function GestureOverlay() {
  const { wakeState, lastEvent } = useGesture();
  if (wakeState === 'sleeping') return null;

  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20,
      width: 160, padding: 8,
      background: 'rgba(15,15,30,0.7)', color: '#cce',
      border: '1px solid #4af', borderRadius: 8,
      fontFamily: 'monospace', fontSize: 11,
      pointerEvents: 'none', zIndex: 1000,
    }}>
      <div>{wakeState.toUpperCase()}</div>
      {lastEvent && (
        <>
          <div>pose: {lastEvent.pose}</div>
          {lastEvent.motion && lastEvent.motion.kind !== 'none' && (
            <div>{lastEvent.motion.kind} {lastEvent.motion.direction || ''}</div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Wire `GestureProvider` into `App.jsx`**

In `apps/luna-client/src/App.jsx`, import and wrap. Add an `onAction` handler that dispatches based on `action.kind`:

```jsx
import { GestureProvider } from './context/GestureContext';
import GestureOverlay from './components/gestures/GestureOverlay';

function handleGestureAction(binding, event) {
  switch (binding.action.kind) {
    case 'nav_hud':         /* call invoke('open_spatial_hud') or window navigation */ break;
    case 'nav_chat':        window.location.hash = '#/chat'; break;
    case 'nav_command_palette': window.dispatchEvent(new Event('luna-open-command-palette')); break;
    case 'agent_next':      window.dispatchEvent(new Event('luna-agent-next')); break;
    case 'agent_prev':      window.dispatchEvent(new Event('luna-agent-prev')); break;
    case 'dismiss':         window.dispatchEvent(new Event('luna-dismiss')); break;
    case 'memory_record':   window.dispatchEvent(new CustomEvent('luna-memory-record', { detail: event })); break;
    default: console.debug('[gesture] unhandled action', binding.action);
  }
}
```

Wrap inside `AuthProvider`:

```jsx
<AuthProvider>
  <GestureProvider onAction={handleGestureAction}>
    <App />
    <GestureOverlay />
  </GestureProvider>
</AuthProvider>
```

- [ ] **Step 8: Migrate `KnowledgeNebula.jsx`**

In `apps/luna-client/src/components/spatial/KnowledgeNebula.jsx` lines 123/128, replace the `luna-gesture-move` window listener with a `useGesture()` consumer. The replacement pattern:

```jsx
import { useGesture } from '../../hooks/useGesture';

// inside the component:
const { lastEvent } = useGesture();
useEffect(() => {
  if (!lastEvent || lastEvent.pose !== 'point' || !lastEvent.motion) return;
  // map motion deltas to camera move; preserve the previous dx/dy/dz contract
  handleGestureMove({
    detail: {
      dx: (lastEvent.motion.direction === 'right' ? 1 : lastEvent.motion.direction === 'left' ? -1 : 0) * 20,
      dy: (lastEvent.motion.direction === 'up' ? 1 : lastEvent.motion.direction === 'down' ? -1 : 0) * 20,
      dz: 0,
    },
  });
}, [lastEvent]);
```

Remove the previous `window.addEventListener('luna-gesture-move', ...)` block.

- [ ] **Step 9: Audit zero remaining `luna-gesture-move` consumers**

```bash
grep -rln "luna-gesture-move" apps/luna-client/src
```

Expected: empty.

- [ ] **Step 10: Commit + push**

```bash
git add -A apps/luna-client/src
git commit -m "feat(luna): GestureProvider + useGesture + GestureOverlay; migrate KnowledgeNebula"
git push && gh run watch
```

---

## Task 1.16: End-to-end smoke test runbook

**Files:** none (manual test).

- [ ] **Step 1: Wait for the macOS DMG build to land in GitHub Releases (CI)**

```bash
gh run watch
gh release view --json assets
```

- [ ] **Step 2: Download + install the DMG, launch Luna**

- [ ] **Step 3: Run the smoke checklist**

Document results in a comment on the PR. Required checks:

1. ✅ Camera permission prompt appears on first launch and the dot indicator becomes "dim" (sleeping).
2. ✅ Open palm held for 500ms transitions dot to "armed" (red) and shows the GestureOverlay.
3. ✅ 3-finger swipe up triggers `nav_hud` (HUD window opens).
4. ✅ 3-finger swipe right cycles to next agent (event log shows `luna-agent-next`).
5. ✅ Idle 5s returns to "sleeping" (dot dims).
6. ✅ `Cmd+Shift+G` toggles paused state — camera light goes out within 200ms.
7. ✅ `KnowledgeNebula` still responds to point-gesture motion in the Spatial HUD.

If any check fails, file a follow-up task and **do not** proceed to Phase 1 review until fixed.

- [ ] **Step 4: Update Phase 1 task status in the PR**

---

## Task 1.17: Phase 1 code review

- [ ] **Step 1: Push final Phase 1 state**

Confirm branch is up to date and CI is green:

```bash
git push
gh run list --branch feat/luna-gesture-system --limit 3
```

- [ ] **Step 2: Open the PR (draft)**

```bash
gh pr create --draft --title "feat(luna): hand-gesture interaction system — Phase 1 (engine + grammar)" \
  --body "$(cat <<'EOF'
## Summary
- In-process Rust gesture engine (Apple Vision FFI) with wake-state machine
- Pose + motion classification with unit tests
- Tauri commands + Cmd+Shift+G killswitch
- React GestureProvider/useGesture/GestureOverlay
- KnowledgeNebula migrated off luna-gesture-move
- API: GET/PUT /users/me/gesture-bindings + migration 114

## Test plan
- [ ] CI green on feat/luna-gesture-system
- [ ] Smoke checklist (see PR comment)
EOF
)"
```

- [ ] **Step 3: Dispatch code-reviewer subagent**

Use the `superpowers:code-reviewer` agent with prompt:

> Review Phase 1 of the Luna gesture system PR (commits since branch start through HEAD on `feat/luna-gesture-system`). Spec at `docs/plans/2026-05-03-luna-gesture-system-design.md`. Verify:
> - Migration 114 applied cleanly and matches spec.
> - Pydantic schema enforces enum + 100-binding cap.
> - Endpoints rate-limited via `slowapi` and 64KB-capped.
> - Rust engine compiles in CI for macOS arm64.
> - Pose/motion/wake unit tests pass.
> - `luna-gesture-move` event is gone.
> - GestureProvider wraps `App.jsx` and `KnowledgeNebula` migrated.
> Report APPROVED or ISSUES FOUND.

- [ ] **Step 4: Address any issues, re-dispatch until APPROVED**

- [ ] **Step 5: Mark Phase 1 complete in PR description**

---

# Phase 2 — Bindings UI (week 2)

**Phase goal:** Users can record custom gestures, bind them to any action, see conflict warnings, toggle scope, and bindings sync to API on save. Memory + RL audit logs are written when an action fires.

**Phase exit gate:** Code-review subagent approves Phase 2 commits + manual test of binding-record-and-sync flow on Mac M4.

## Task 2.1: `useGestureBindings` hook (load/save/CRUD with API sync)

**Files:**
- Create: `apps/luna-client/src/hooks/useGestureBindings.js`
- Modify: `apps/luna-client/src/api.js`
- Create: `apps/luna-client/src/components/gestures/__tests__/useGestureBindings.test.js`

- [ ] **Step 1: Add API helpers**

Append to `apps/luna-client/src/api.js`:

```js
export async function getGestureBindings(token) {
  const res = await fetch(`${baseURL()}/api/v1/users/me/gesture-bindings`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`getGestureBindings ${res.status}`);
  return res.json();
}

export async function saveGestureBindings(token, bindings) {
  const res = await fetch(`${baseURL()}/api/v1/users/me/gesture-bindings`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ bindings }),
  });
  if (!res.ok) throw new Error(`saveGestureBindings ${res.status}`);
}
```

(Reuse the existing `baseURL()` helper.)

- [ ] **Step 2: Write failing hook test**

```js
import { describe, it, expect, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useGestureBindings } from '../../../hooks/useGestureBindings';

vi.mock('../../../api', () => ({
  getGestureBindings: vi.fn(async () => ({ bindings: [], updated_at: null })),
  saveGestureBindings: vi.fn(async () => undefined),
}));

vi.mock('../../../context/AuthContext', () => ({
  useAuth: () => ({ token: 'test-token' }),
}));

describe('useGestureBindings', () => {
  it('loads defaults when API returns empty', async () => {
    const { result } = renderHook(() => useGestureBindings());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.bindings.length).toBeGreaterThan(0); // defaults seeded
  });

  it('detects conflicts on overlapping gesture+scope', async () => {
    const { result } = renderHook(() => useGestureBindings());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const dup = { ...result.current.bindings[0], id: 'new', enabled: true };
    expect(result.current.detectConflict(dup)).toBe(true);
  });
});
```

- [ ] **Step 3: Implement the hook**

```js
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { getGestureBindings, saveGestureBindings } from '../api';
import { DEFAULT_BINDINGS } from '../components/gestures/defaults';

export function useGestureBindings() {
  const { token } = useAuth();
  const [bindings, setBindings] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await getGestureBindings(token);
        setBindings(res.bindings.length ? res.bindings : DEFAULT_BINDINGS);
      } catch (e) {
        setError(e);
        setBindings(DEFAULT_BINDINGS);
      } finally {
        setLoaded(true);
      }
    })();
  }, [token]);

  const sameGesture = (a, b) => (
    a.gesture.pose === b.gesture.pose &&
    JSON.stringify(a.gesture.motion || null) === JSON.stringify(b.gesture.motion || null) &&
    a.scope === b.scope
  );

  const detectConflict = useCallback((candidate) => (
    bindings.some((b) => b.id !== candidate.id && b.enabled && candidate.enabled && sameGesture(b, candidate))
  ), [bindings]);

  const upsert = useCallback(async (binding) => {
    const next = (() => {
      const idx = bindings.findIndex((b) => b.id === binding.id);
      if (idx >= 0) { const arr = [...bindings]; arr[idx] = binding; return arr; }
      return [...bindings, binding];
    })();
    setBindings(next);
    if (token) await saveGestureBindings(token, next);
  }, [bindings, token]);

  const remove = useCallback(async (id) => {
    const next = bindings.filter((b) => b.id !== id);
    setBindings(next);
    if (token) await saveGestureBindings(token, next);
  }, [bindings, token]);

  const resetToDefaults = useCallback(async () => {
    setBindings(DEFAULT_BINDINGS);
    if (token) await saveGestureBindings(token, DEFAULT_BINDINGS);
  }, [token]);

  return { bindings, loaded, error, detectConflict, upsert, remove, resetToDefaults };
}
```

- [ ] **Step 4: Push, watch CI tests**

```bash
git add apps/luna-client/src/api.js apps/luna-client/src/hooks/useGestureBindings.js apps/luna-client/src/components/gestures/__tests__/useGestureBindings.test.js
git commit -m "feat(luna): useGestureBindings hook with conflict detection + API sync"
git push && gh run watch
```

---

## Task 2.2: `GestureBindingsPage` and `GestureBindingRow`

**Files:**
- Create: `apps/luna-client/src/components/gestures/GestureBindingsPage.jsx`
- Create: `apps/luna-client/src/components/gestures/GestureBindingRow.jsx`
- Create: `apps/luna-client/src/components/gestures/__tests__/GestureBindingsPage.test.jsx`
- Modify: `apps/luna-client/src/App.jsx` (add `/settings/gestures` route)

- [ ] **Step 1: Failing render test**

```jsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import GestureBindingsPage from '../GestureBindingsPage';

vi.mock('../../../hooks/useGestureBindings', () => ({
  useGestureBindings: () => ({
    bindings: [
      { id: 'b1', gesture: { pose: 'open_palm' }, action: { kind: 'nav_hud' }, scope: 'global', enabled: true, user_recorded: false },
    ],
    loaded: true, error: null,
    detectConflict: () => false, upsert: vi.fn(), remove: vi.fn(), resetToDefaults: vi.fn(),
  }),
}));

describe('GestureBindingsPage', () => {
  it('renders bindings list', () => {
    render(<GestureBindingsPage />);
    expect(screen.getByText(/open_palm/i)).toBeInTheDocument();
    expect(screen.getByText(/nav_hud/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement the page + row**

`GestureBindingRow.jsx`:

```jsx
import React from 'react';

export default function GestureBindingRow({ binding, conflict, onEdit, onToggle, onDelete }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: 8,
      borderBottom: '1px solid #233', opacity: binding.enabled ? 1 : 0.55,
    }}>
      <div style={{ flex: 1 }}>
        <div><b>{binding.gesture.pose}</b>{binding.gesture.motion ? ` + ${binding.gesture.motion.kind} ${binding.gesture.motion.direction || ''}` : ''}</div>
        <div style={{ fontSize: 12, color: '#9ad' }}>{binding.action.kind} ({binding.scope})</div>
        {conflict && <div style={{ color: '#fa6', fontSize: 11 }}>⚠ conflict with another active binding</div>}
      </div>
      <button onClick={() => onToggle(binding)}>{binding.enabled ? 'Disable' : 'Enable'}</button>
      <button onClick={() => onEdit(binding)}>Edit</button>
      <button onClick={() => onDelete(binding.id)}>Delete</button>
    </div>
  );
}
```

`GestureBindingsPage.jsx`:

```jsx
import React, { useState } from 'react';
import { useGestureBindings } from '../../hooks/useGestureBindings';
import GestureBindingRow from './GestureBindingRow';
import GestureRecorder from './GestureRecorder';

export default function GestureBindingsPage() {
  const { bindings, loaded, error, detectConflict, upsert, remove, resetToDefaults } = useGestureBindings();
  const [editing, setEditing] = useState(null);

  if (!loaded) return <div style={{ padding: 24 }}>Loading bindings…</div>;

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <h2>Gesture Bindings</h2>
      {error && <div style={{ color: '#f55' }}>Error loading: {String(error.message || error)}</div>}
      <div style={{ margin: '12px 0' }}>
        <button onClick={resetToDefaults}>Reset to defaults</button>
        <button onClick={() => setEditing({})} style={{ marginLeft: 8 }}>+ New binding</button>
      </div>
      {bindings.map((b) => (
        <GestureBindingRow
          key={b.id} binding={b}
          conflict={detectConflict(b)}
          onEdit={setEditing}
          onToggle={(bd) => upsert({ ...bd, enabled: !bd.enabled })}
          onDelete={remove}
        />
      ))}
      {editing !== null && (
        <GestureRecorder
          initial={editing}
          onSave={(b) => { upsert(b); setEditing(null); }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add the route in `App.jsx`**

```jsx
import GestureBindingsPage from './components/gestures/GestureBindingsPage';

// inside the Routes:
<Route path="/settings/gestures" element={<GestureBindingsPage />} />
```

- [ ] **Step 4: Push, CI green**

```bash
git add apps/luna-client/src/components/gestures/GestureBindingsPage.jsx apps/luna-client/src/components/gestures/GestureBindingRow.jsx apps/luna-client/src/components/gestures/__tests__/GestureBindingsPage.test.jsx apps/luna-client/src/App.jsx
git commit -m "feat(luna): GestureBindingsPage + Row with edit/toggle/delete + /settings/gestures route"
git push && gh run watch
```

---

## Task 2.3: `GestureRecorder` modal — capture-3-times flow

**Files:**
- Create: `apps/luna-client/src/components/gestures/GestureRecorder.jsx`

- [ ] **Step 1: Implement the recorder**

```jsx
import React, { useEffect, useState } from 'react';
import { useGesture } from '../../hooks/useGesture';

const ACTION_KINDS = [
  'memory_recall', 'memory_record', 'nav_chat', 'nav_hud', 'nav_command_palette',
  'agent_next', 'agent_prev', 'workflow_run', 'approve', 'dismiss',
  'mic_toggle', 'scroll_up', 'scroll_down', 'zoom_in', 'zoom_out',
  'cursor_move', 'click', 'mcp_tool', 'skill', 'custom',
];

export default function GestureRecorder({ initial, onSave, onCancel }) {
  const { lastEvent } = useGesture();
  const [samples, setSamples] = useState([]);
  const [actionKind, setActionKind] = useState(initial?.action?.kind || 'nav_hud');
  const [scope, setScope] = useState(initial?.scope || 'global');

  useEffect(() => {
    if (lastEvent && samples.length < 3) {
      setSamples((s) => [...s, lastEvent]);
    }
  }, [lastEvent]);

  const consensus = samples.length === 3 ? {
    pose: samples[0].pose,
    motion: samples[0].motion,
  } : null;

  const handleSave = () => {
    if (!consensus) return;
    const id = initial?.id || `u-${Date.now()}`;
    onSave({
      id,
      gesture: { pose: consensus.pose, motion: consensus.motion },
      action: { kind: actionKind },
      scope,
      enabled: true,
      user_recorded: true,
    });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,10,0.85)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000,
    }}>
      <div style={{ background: '#0a1024', padding: 24, borderRadius: 12, minWidth: 360, color: '#cce' }}>
        <h3>Record gesture ({samples.length}/3)</h3>
        <p>Perform the gesture three times. The wake state must be ARMED.</p>
        <pre style={{ background: '#001020', padding: 8, fontSize: 12, minHeight: 80 }}>
          {samples.map((s, i) => `${i+1}. ${s.pose}${s.motion?.kind ? ' ' + s.motion.kind + ' ' + (s.motion.direction || '') : ''}`).join('\n') || 'waiting…'}
        </pre>
        <label>Action: <select value={actionKind} onChange={(e) => setActionKind(e.target.value)}>
          {ACTION_KINDS.map((k) => <option key={k}>{k}</option>)}
        </select></label>
        <label style={{ marginLeft: 12 }}>Scope: <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option>global</option><option>luna_only</option><option>hud_only</option><option>chat_only</option>
        </select></label>
        <div style={{ marginTop: 16 }}>
          <button onClick={onCancel}>Cancel</button>
          <button onClick={handleSave} disabled={!consensus} style={{ marginLeft: 8 }}>Save</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit + push**

```bash
git add apps/luna-client/src/components/gestures/GestureRecorder.jsx
git commit -m "feat(luna): GestureRecorder modal — capture 3 samples then bind"
git push && gh run watch
```

---

## Task 2.4: Server-side audit + RL on action dispatch

**Files:**
- Create: `apps/api/app/api/v1/gesture_dispatch.py` (a small action-event endpoint the client posts to)
- Modify: `apps/api/app/api/v1/routes.py` (mount it)

- [ ] **Step 1: Failing test**

In `apps/api/tests/test_gesture_bindings.py`:

```python
def test_dispatch_logs_memory_activity_and_rl(db_session, test_user, client, auth_headers):
    payload = {
        "binding_id": "b1",
        "gesture": {"pose": "three", "motion": {"kind": "swipe", "direction": "up"}},
        "action_kind": "nav_hud",
        "screen": "/chat",
        "frontmost_app": "Luna",
        "latency_ms": 42,
        "confidence": 0.92,
    }
    r = client.post("/api/v1/gesture-dispatch", json=payload, headers=auth_headers)
    assert r.status_code in (200, 204)

    from app.models.memory_activity import MemoryActivity
    from app.models.rl_experience import RLExperience
    assert db_session.query(MemoryActivity).filter(
        MemoryActivity.tenant_id == test_user.tenant_id,
        MemoryActivity.event_type == "gesture_triggered",
    ).count() >= 1
    assert db_session.query(RLExperience).filter(
        RLExperience.tenant_id == test_user.tenant_id,
        RLExperience.decision_point == "gesture_action",
    ).count() >= 1
```

- [ ] **Step 2: Implement the route**

```python
"""Gesture dispatch — logs audit + RL when the client fires a binding."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User as UserModel
from app.services import memory_activity, rl_experience_service

router = APIRouter()


class GestureDispatch(BaseModel):
    binding_id: str
    gesture: dict
    action_kind: str
    screen: Optional[str] = None
    frontmost_app: Optional[str] = None
    latency_ms: Optional[int] = None
    confidence: Optional[float] = None


@router.post("/gesture-dispatch", status_code=204)
def dispatch(
    payload: GestureDispatch,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    try:
        memory_activity.log_activity(
            db, current_user.tenant_id,
            event_type="gesture_triggered",
            description=f"{payload.action_kind} via {payload.gesture.get('pose')}",
            source="gesture",
            event_metadata={
                "gesture": payload.gesture,
                "action_kind": payload.action_kind,
                "binding_id": payload.binding_id,
                "screen": payload.screen,
                "frontmost_app": payload.frontmost_app,
            },
        )
    except Exception:
        pass
    try:
        rl_experience_service.log_experience(
            db, current_user.tenant_id,
            trajectory_id=str(uuid.uuid4()),
            step_index=0,
            decision_point="gesture_action",
            state={
                "screen": payload.screen,
                "frontmost_app": payload.frontmost_app,
                "binding_id": payload.binding_id,
            },
            action={"kind": payload.action_kind},
        )
    except Exception:
        pass
    db.commit()
    return None
```

Mount in `routes.py`:

```python
from . import gesture_dispatch
router.include_router(gesture_dispatch.router, tags=["gestures"])
```

- [ ] **Step 3: Push, run tests**

```bash
git add apps/api/app/api/v1/gesture_dispatch.py apps/api/app/api/v1/routes.py apps/api/tests/test_gesture_bindings.py
git commit -m "feat(api): /gesture-dispatch endpoint logs MemoryActivity + RL experience"
git push && gh run watch
```

---

## Task 2.5: Client posts to `/gesture-dispatch` on action

**Files:**
- Modify: `apps/luna-client/src/api.js`
- Modify: `apps/luna-client/src/App.jsx` (`handleGestureAction`)

- [ ] **Step 1: Add helper**

```js
export async function postGestureDispatch(token, payload) {
  await fetch(`${baseURL()}/api/v1/gesture-dispatch`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}
```

- [ ] **Step 2: Wire into `handleGestureAction`**

```jsx
import { postGestureDispatch } from './api';
import { useAuth } from './context/AuthContext';

// inside the component that defines handleGestureAction (lift to a function-component hook):
const { token } = useAuth();
const handleGestureAction = useCallback((binding, event) => {
  postGestureDispatch(token, {
    binding_id: binding.id,
    gesture: binding.gesture,
    action_kind: binding.action.kind,
    screen: window.location.hash,
    confidence: event.confidence,
  });
  // existing dispatch switch...
}, [token]);
```

- [ ] **Step 3: Commit + push**

```bash
git add apps/luna-client/src/api.js apps/luna-client/src/App.jsx
git commit -m "feat(luna): client posts gesture dispatch events for audit + RL"
git push && gh run watch
```

---

## Task 2.6: Web SettingsPage stub for read-only Gestures section

**Files:**
- Modify: `apps/web/src/pages/SettingsPage.js`

- [ ] **Step 1: Add a read-only subsection**

In `SettingsPage.js`, append a panel:

```jsx
<section>
  <h3>Gestures</h3>
  <p>Configure hand-gesture bindings in the Luna desktop app. Last synced: {syncedAt || 'never'}.</p>
  <a href="luna://open/settings/gestures">Open in Luna</a>
</section>
```

(`syncedAt` comes from `GET /users/me/gesture-bindings` over the existing axios client.)

- [ ] **Step 2: Commit + push**

```bash
git add apps/web/src/pages/SettingsPage.js
git commit -m "feat(web): read-only Gestures subsection on Settings page"
git push && gh run watch
```

---

## Task 2.7: Phase 2 code review

- [ ] **Step 1: Update PR description with Phase 2 scope.**
- [ ] **Step 2: Dispatch `superpowers:code-reviewer`** — review commits since the Phase 1 review tag through HEAD. Verify:
  - `useGestureBindings` correctly handles API failure → falls back to defaults.
  - `GestureRecorder` only saves when 3 samples agree.
  - `/gesture-dispatch` writes both audit + RL rows; failures are swallowed.
  - Web `SettingsPage` deep-link works.
- [ ] **Step 3: Address feedback, re-dispatch until APPROVED.**

---

# Phase 3 — Extensions (week 3)

**Phase goal:** Cursor (luna_only by default + opt-in global), hand-rotation knob, two-handed frame, calibration wizard, motion analyzer extended with pinch/rotate/tap.

**Phase exit gate:** Code review approves + smoke test passes (cursor tracks <16ms p95, calibration recorded, rotation knob drives chat zoom).

## Task 3.1: Extend motion analyzer (pinch/rotate/tap)

**Files:**
- Modify: `apps/luna-client/src-tauri/src/gesture/motion.rs`
- Add tests: `tests/motion_test.rs`

- [ ] **Step 1: Add failing tests**

```rust
#[test]
fn detects_pinch_in() {
    let mut a = MotionAnalyzer::new();
    // synthetic: thumb tip (4) and index tip (8) approaching each other
    for i in 0..15 {
        let mut frame = frame_at(0.5, 0.5);
        let d = 0.30 - (i as f32) * 0.02;
        frame.landmarks[4] = Landmark { x: 0.5 - d/2.0, y: 0.5, z: 0.0 };
        frame.landmarks[8] = Landmark { x: 0.5 + d/2.0, y: 0.5, z: 0.0 };
        a.push(&frame, 1700_000_000_000 + (i as i64) * 33);
    }
    let m = a.classify().unwrap();
    assert_eq!(m.kind, MotionKind::Pinch);
    assert_eq!(m.direction, Some(Direction::In));
}
```

- [ ] **Step 2: Extend `MotionAnalyzer::classify`** to compute thumb-index distance derivatives and palm-normal angular delta. Implementation per spec — returns Pinch / Rotate / Tap accordingly.

- [ ] **Step 3: Push + CI green**

```bash
git add apps/luna-client/src-tauri/src/gesture/motion.rs apps/luna-client/src-tauri/src/gesture/tests/
git commit -m "feat(luna): motion analyzer pinch/rotate/tap detection"
git push && gh run watch
```

---

## Task 3.2: `cursor.rs` — Accessibility-gated system cursor

**Files:**
- Create: `apps/luna-client/src-tauri/src/gesture/cursor.rs`
- Modify: `apps/luna-client/src-tauri/Cargo.toml` (add `enigo = "0.2"`)
- Modify: `apps/luna-client/src-tauri/src/gesture/supervisor.rs` (call cursor on Point + motion when armed and binding active)

- [ ] **Step 1: Implement `cursor.rs`**

```rust
use enigo::{Enigo, Mouse, Settings, Coordinate};

pub struct CursorDriver {
    enigo: Option<Enigo>,
    accessibility_ok: bool,
    global_mode: bool,
}

#[cfg(target_os = "macos")]
fn accessibility_check() -> bool {
    use std::process::Command;
    Command::new("osascript")
        .args(["-e", "tell application \"System Events\" to get name of first process"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

impl CursorDriver {
    pub fn new(global_mode: bool) -> Self {
        let accessibility_ok = accessibility_check();
        let enigo = if accessibility_ok { Enigo::new(&Settings::default()).ok() } else { None };
        Self { enigo, accessibility_ok, global_mode }
    }

    pub fn move_abs(&mut self, x: f32, y: f32, frontmost_is_luna: bool) {
        if !self.accessibility_ok { return; }
        if !self.global_mode && !frontmost_is_luna { return; }
        if let Some(e) = self.enigo.as_mut() {
            // x, y in 0..1 normalized; map to display
            // Display size detection: deferred; use 1920×1080 placeholder for v1.
            let _ = e.move_mouse((x * 1920.0) as i32, (y * 1080.0) as i32, Coordinate::Abs);
        }
    }

    pub fn click(&mut self, frontmost_is_luna: bool) {
        if !self.accessibility_ok { return; }
        if !self.global_mode && !frontmost_is_luna { return; }
        if let Some(e) = self.enigo.as_mut() {
            let _ = e.button(enigo::Button::Left, enigo::Direction::Click);
        }
    }
}
```

- [ ] **Step 2: Wire into the engine loop** when binding action is `cursor_move` or `click` (lookup binding registry from JS-side via Tauri command, or include defaults in supervisor).

(Concrete wiring: a `gesture_set_cursor_mode(global: bool)` Tauri command updates a static `CURSOR_GLOBAL_MODE: AtomicBool`; the recognizer task instantiates `CursorDriver` once and calls `move_abs` on point-pose frames.)

- [ ] **Step 3: Push + CI**

```bash
git add apps/luna-client/src-tauri/Cargo.toml apps/luna-client/src-tauri/src/gesture/cursor.rs apps/luna-client/src-tauri/src/gesture/supervisor.rs apps/luna-client/src-tauri/src/lib.rs
git commit -m "feat(luna): system cursor driver via enigo with Accessibility + frontmost gates"
git push && gh run watch
```

---

## Task 3.3: `LunaCursor.jsx` overlay

**Files:**
- Create: `apps/luna-client/src/components/luna/LunaCursor.jsx`
- Modify: `apps/luna-client/src/App.jsx` (mount the overlay)

- [ ] **Step 1: Implement the in-app overlay**

```jsx
import React from 'react';
import { useGesture } from '../../hooks/useGesture';

export default function LunaCursor() {
  const { wakeState, lastEvent } = useGesture();
  if (wakeState !== 'armed' || !lastEvent || lastEvent.pose !== 'point') return null;
  // Overlay-only feedback; system cursor moved by Rust
  const x = (lastEvent.fingers_extended ? 0.5 : 0.5) * window.innerWidth;
  const y = 0.5 * window.innerHeight;
  return (
    <div style={{
      position: 'fixed', left: x - 6, top: y - 6,
      width: 12, height: 12, borderRadius: 6,
      background: 'rgba(120,200,255,0.6)', boxShadow: '0 0 12px #4cf',
      pointerEvents: 'none', zIndex: 1500,
    }} />
  );
}
```

(For v1 the overlay is informational; the actual cursor updates come from Rust.)

- [ ] **Step 2: Mount + commit**

```bash
git add apps/luna-client/src/components/luna/LunaCursor.jsx apps/luna-client/src/App.jsx
git commit -m "feat(luna): LunaCursor in-app overlay (decorative; system cursor driven by Rust)"
git push && gh run watch
```

---

## Task 3.4: `GestureCalibration` first-launch wizard

**Files:**
- Create: `apps/luna-client/src/components/gestures/GestureCalibration.jsx`
- Modify: `apps/luna-client/src/App.jsx` (first-launch detection)

- [ ] **Step 1: Implement the wizard component**

```jsx
import React, { useState } from 'react';
import { useGesture } from '../../hooks/useGesture';

const STEPS = [
  { key: 'camera', title: 'Camera permission', body: 'Luna needs your camera to recognize hand gestures. Click Allow when macOS asks.' },
  { key: 'select', title: 'Choose a camera', body: 'Pick the camera you want to use.' },
  { key: 'access', title: 'Accessibility (optional)', body: 'Grant Accessibility if you want gestures to control the cursor outside Luna. Skip otherwise.' },
  { key: 'pose', title: 'Pose tutorial', body: 'Show me an open palm, then a fist, then point, peace, and five.' },
  { key: 'wake', title: 'Wake-gesture practice', body: 'Hold an open palm for half a second to wake Luna.' },
  { key: 'tour', title: 'Bindings tour', body: '3-finger swipe up = Spatial HUD, 4-finger pinch = Command Palette, fist = dismiss.' },
];

export default function GestureCalibration({ onDone }) {
  const [step, setStep] = useState(0);
  const { wakeState } = useGesture();
  const cur = STEPS[step];

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#001020',
      display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#cce', zIndex: 3000 }}>
      <div style={{ maxWidth: 480, padding: 24, border: '1px solid #345', borderRadius: 12 }}>
        <h2>{cur.title}</h2>
        <p>{cur.body}</p>
        <div style={{ fontSize: 12, color: '#69a' }}>Wake state: {wakeState}</div>
        <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
          {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
          {step < STEPS.length - 1
            ? <button onClick={() => setStep(step + 1)}>Next</button>
            : <button onClick={() => { localStorage.setItem('gestureCalibrated', '1'); onDone(); }}>Done</button>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: First-launch trigger in `App.jsx`**

```jsx
const [showCalibration, setShowCalibration] = useState(
  () => !localStorage.getItem('gestureCalibrated')
);

// inside the JSX:
{showCalibration && <GestureCalibration onDone={() => setShowCalibration(false)} />}
```

- [ ] **Step 3: Commit + push**

```bash
git add apps/luna-client/src/components/gestures/GestureCalibration.jsx apps/luna-client/src/App.jsx
git commit -m "feat(luna): first-launch GestureCalibration wizard"
git push && gh run watch
```

---

## Task 3.5: Phase 3 code review + final PR ready-for-review

- [ ] **Step 1: Smoke test all extensions on Mac M4**

Checklist:
1. ✅ Calibration wizard appears on first launch.
2. ✅ Pinch in/out detected.
3. ✅ Cursor moves only inside Luna by default; toggling `cursor_global_mode` makes it move system-wide (after Accessibility granted).
4. ✅ Rotation knob increments chat zoom smoothly.

- [ ] **Step 2: Dispatch code reviewer** for Phase 3 commits. Verify:
- Cursor never fires when frontmost ≠ Luna unless `cursor_global_mode` is on.
- Calibration writes the `gestureCalibrated` flag.
- Motion analyzer pinch/rotate/tap logic matches the spec.

- [ ] **Step 3: Mark PR ready for review** (`gh pr ready`). Assign to `nomade` (per global CLAUDE.md). Tag any reviewers per project convention.

- [ ] **Step 4: Mark Phase 3 complete in PR description.**

---

## Final Definition of Done

- All three phases complete; PR `feat/luna-gesture-system` is ready for review and assigned to `nomade`.
- CI green on all commits.
- Migration 114 applied in local + (when promoted) CI environments.
- Smoke checklist passed on a Mac M4 DMG produced by CI.
- Code reviewer (`superpowers:code-reviewer`) returned APPROVED for each phase.
- No `luna-gesture-move` references remain in the codebase.
- No new tables; reuse map honored.
- No local Tauri builds; everything went through CI.
