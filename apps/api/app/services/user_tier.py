"""User den-tier helpers (Alpha Control Plane PR-4 of 7).

Tier 0-5 controls how much of the Den UI a user sees. Stored in
`user_preferences` with `preference_type='alpha_den_tier'` — no
migration needed (see design §4 → "Tier storage").

Uses raw SQL rather than the UserPreference ORM model so this stays
safe against ORM-vs-schema drift on optional columns like `value_json`
that aren't always present across environments.

Design: docs/plans/2026-05-15-alpha-control-plane-design.md §4
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import text
from sqlalchemy.orm import Session

_PREFERENCE_TYPE: Final = "alpha_den_tier"
VALID_TIERS: Final = frozenset({0, 1, 2, 3, 4, 5})
DEFAULT_TIER: Final = 0


class InvalidTierError(ValueError):
    """Raised when a caller passes a tier outside 0..5."""


def get_tier(db: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    """Return the user's current den tier.

    Defaults to 0 when no preference row exists or when the stored
    value is corrupted (non-integer, out of range).
    """
    row = db.execute(
        text(
            "SELECT value FROM user_preferences "
            "WHERE user_id = :uid AND tenant_id = :tid AND preference_type = :ptype"
        ),
        {"uid": user_id, "tid": tenant_id, "ptype": _PREFERENCE_TYPE},
    ).first()
    if not row or row[0] is None:
        return DEFAULT_TIER
    try:
        tier = int(row[0])
    except (TypeError, ValueError):
        return DEFAULT_TIER
    return tier if tier in VALID_TIERS else DEFAULT_TIER


def set_tier(db: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID, tier: int) -> int:
    """Upsert the user's den tier and return the persisted value.

    Raises InvalidTierError for tier outside 0..5 or non-int.
    Commits the change.
    """
    # Hard-validate. Non-int and out-of-range both reject here.
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in VALID_TIERS:
        raise InvalidTierError(
            f"Invalid tier {tier!r}; must be one of {sorted(VALID_TIERS)}"
        )

    # Try UPDATE first; if no row, INSERT. Cheaper than SELECT-then-branch
    # for the steady-state case.
    now = datetime.utcnow()
    result = db.execute(
        text(
            "UPDATE user_preferences "
            "SET value = :val, updated_at = :ts "
            "WHERE user_id = :uid AND tenant_id = :tid AND preference_type = :ptype"
        ),
        {
            "val": str(tier), "ts": now,
            "uid": user_id, "tid": tenant_id, "ptype": _PREFERENCE_TYPE,
        },
    )
    if result.rowcount == 0:
        db.execute(
            text(
                "INSERT INTO user_preferences "
                "(id, tenant_id, user_id, preference_type, value, updated_at) "
                "VALUES (:id, :tid, :uid, :ptype, :val, :ts)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant_id, "uid": user_id,
                "ptype": _PREFERENCE_TYPE, "val": str(tier), "ts": now,
            },
        )
    db.commit()
    return tier
