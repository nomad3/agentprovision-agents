"""Service for reading/writing user gesture bindings.

Bindings are stored in `user_preferences` with `preference_type='gesture_bindings'` and
the binding list serialized into the `value_json` JSONB column (added in migration 114).
The simple `value` String column is left NULL for gesture-bindings rows.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.user_preference import UserPreference

PREFERENCE_TYPE = "gesture_bindings"


def _query(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
    return (
        db.query(UserPreference)
        .filter(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.preference_type == PREFERENCE_TYPE,
        )
    )


def get_bindings_for_user(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> List[dict]:
    row = _query(db, tenant_id, user_id).first()
    if not row or not row.value_json:
        return []
    return row.value_json.get("bindings", [])


def get_bindings_metadata(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[datetime]:
    row = _query(db, tenant_id, user_id).first()
    return row.updated_at if row else None


def save_bindings_for_user(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    bindings: List[dict],
) -> None:
    row = _query(db, tenant_id, user_id).first()
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
