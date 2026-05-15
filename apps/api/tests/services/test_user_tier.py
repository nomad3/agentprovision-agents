"""Tests for app.services.user_tier (PR-4 of Alpha Control Plane Tier 0-1).

Covers get/set semantics, default-0 behaviour, corruption tolerance,
range validation, and tenant isolation.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytest.importorskip("sqlalchemy")


@pytest.fixture
def engine():
    return create_engine(os.environ["DATABASE_URL"])


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def tenant_and_user(engine):
    """Real tenants + users row for the test (UserPreference FKs require them)."""
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'tier-test')"), {"id": tid})
        c.execute(
            text("INSERT INTO users (id, tenant_id, email, hashed_password, is_active) "
                 "VALUES (:id, :tid, :email, 'x', true)"),
            {"id": uid, "tid": tid, "email": f"tier-{uid}@test.local"},
        )
    yield tid, uid
    with engine.begin() as c:
        c.execute(text("DELETE FROM user_preferences WHERE user_id = :uid"), {"uid": uid})
        c.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
        c.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tid})


def test_get_tier_defaults_to_zero(db, tenant_and_user):
    """User with no preference row returns tier 0."""
    from app.services.user_tier import get_tier

    tid, uid = tenant_and_user
    assert get_tier(db, user_id=uid, tenant_id=tid) == 0


def test_set_then_get_round_trip(db, tenant_and_user):
    """set_tier upserts; get_tier returns the new value."""
    from app.services.user_tier import get_tier, set_tier

    tid, uid = tenant_and_user
    assert set_tier(db, user_id=uid, tenant_id=tid, tier=3) == 3
    assert get_tier(db, user_id=uid, tenant_id=tid) == 3

    # Setting again replaces the value (upsert, not duplicate row)
    assert set_tier(db, user_id=uid, tenant_id=tid, tier=5) == 5
    assert get_tier(db, user_id=uid, tenant_id=tid) == 5

    row_count = db.execute(
        text("SELECT COUNT(*) FROM user_preferences "
             "WHERE user_id = :uid AND preference_type = 'alpha_cockpit_tier'"),
        {"uid": uid},
    ).scalar()
    assert row_count == 1, "set_tier must upsert, not duplicate"


@pytest.mark.parametrize("bad_value", [-1, 6, 99, "not-an-int", None])
def test_set_tier_rejects_invalid(db, tenant_and_user, bad_value):
    """set_tier raises InvalidTierError for anything outside 0..5."""
    from app.services.user_tier import set_tier, InvalidTierError

    tid, uid = tenant_and_user
    with pytest.raises((InvalidTierError, TypeError)):
        set_tier(db, user_id=uid, tenant_id=tid, tier=bad_value)


def test_get_tier_tolerates_corrupt_value(db, tenant_and_user):
    """If the stored value is non-numeric or out of range, return 0."""
    from app.services.user_tier import get_tier

    tid, uid = tenant_and_user
    # Manually plant a corrupt preference row
    db.execute(
        text("INSERT INTO user_preferences "
             "(id, tenant_id, user_id, preference_type, value, updated_at) "
             "VALUES (:id, :tid, :uid, 'alpha_cockpit_tier', 'banana', NOW())"),
        {"id": uuid.uuid4(), "tid": tid, "uid": uid},
    )
    db.commit()
    assert get_tier(db, user_id=uid, tenant_id=tid) == 0


def test_tenant_isolation(db, engine):
    """Setting tier for user A in tenant X doesn't affect user A's value in tenant Y.

    (Same user_id across tenants is unusual but the join key includes tenant_id;
    we verify the where-clause does its job.)
    """
    from app.services.user_tier import get_tier, set_tier

    uid = uuid.uuid4()
    tid_a = uuid.uuid4()
    tid_b = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'A')"), {"id": tid_a})
        c.execute(text("INSERT INTO tenants (id, name) VALUES (:id, 'B')"), {"id": tid_b})
        c.execute(
            text("INSERT INTO users (id, tenant_id, email, hashed_password, is_active) "
                 "VALUES (:id, :tid, :email, 'x', true)"),
            {"id": uid, "tid": tid_a, "email": f"iso-{uid}@test.local"},
        )

    try:
        set_tier(db, user_id=uid, tenant_id=tid_a, tier=4)
        # Tenant A sees 4, Tenant B sees default 0 (no row for that pair)
        assert get_tier(db, user_id=uid, tenant_id=tid_a) == 4
        assert get_tier(db, user_id=uid, tenant_id=tid_b) == 0
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM user_preferences WHERE user_id = :uid"), {"uid": uid})
            c.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
            c.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": tid_a, "b": tid_b})
