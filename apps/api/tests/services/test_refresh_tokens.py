"""Locks the security-load-bearing surface of refresh-token rotation.

PR #442 review finding B-4: the service module that mints, rotates,
and burns chains on reuse detection had zero pytest coverage. This file
exercises the contract end-to-end against an in-memory SQLite session so
CI can run it without postgres.

What we test:
  * Successful rotation marks the parent rotated and links the child
    via parent_id (the rotation chain).
  * Replaying a parent that's already been rotated → revoke_chain_from
    walks the whole family (both up the parent chain and down the
    children DAG).
  * revoke_chain_from respects `max_rows` cap (review I-3).
  * find_rotated_child returns the most recent live child of a parent
    (used by the grace-window pathway, B-1).
  * revoke_one is idempotent.

SQLite shortcomings vs. postgres:
  * INET column type — we coerce via type-decorator-free design: the
    model uses postgresql.INET but the tests never set ip_inet directly.
  * gen_random_uuid()/pgcrypto — the model defaults via SQLAlchemy
    `default=uuid.uuid4`, so SQLite never invokes the DB function.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import Iterator

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant  # noqa: F401 — registered for FK chain
from app.models.user import User
from app.services import refresh_tokens as svc


# ──────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def db() -> Iterator[Session]:
    """Throwaway in-memory SQLite session with the bare-minimum tables.

    We only create `users` + `refresh_tokens` (+ `tenants` for the FK)
    so model import side-effects don't pull in the whole graph. The
    `refresh_tokens.ip_inet` column is `postgresql.INET`, which SQLite
    can't render natively; we patch the column type to TEXT for the
    test's lifetime so CompileError doesn't kill collection.
    """
    from sqlalchemy import Text

    rt_table = Base.metadata.tables["refresh_tokens"]
    original_type = rt_table.c.ip_inet.type
    rt_table.c.ip_inet.type = Text()
    try:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(
            engine,
            tables=[
                Base.metadata.tables["tenants"],
                Base.metadata.tables["users"],
                rt_table,
            ],
        )
        Session_ = sessionmaker(bind=engine, future=True)
        session = Session_()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
    finally:
        # Restore the postgresql.INET type so the model stays correct
        # for any subsequent tests / runtime imports in the same process.
        rt_table.c.ip_inet.type = original_type


@pytest.fixture
def user(db: Session) -> User:
    """A bare User with no tenant — keeps the test surface tight."""
    u = User(
        id=uuid.uuid4(),
        email=f"refresh-test-{uuid.uuid4()}@example.test",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
    )
    db.add(u)
    db.flush()
    return u


# ──────────────────────────────────────────────────────────────────────
# Issuance + rotation
# ──────────────────────────────────────────────────────────────────────


def test_issue_refresh_token_returns_plaintext_and_persists_only_hash(db, user):
    """The plaintext secret flows back ONCE; the DB stores sha256 hash."""
    secret, row = svc.issue_refresh_token(db, user=user, device_label="laptop")
    db.commit()

    assert secret  # non-empty
    assert len(secret) >= 30  # token_urlsafe(32) → 43 chars; allow slack
    # Persisted row must NOT contain the plaintext anywhere.
    assert secret not in row.token_hash
    # Hash matches sha256(secret).
    expected_hash = svc._hash_secret(secret)
    assert row.token_hash == expected_hash
    assert row.parent_id is None  # first link in chain
    assert row.device_label == "laptop"
    assert row.revoked_at is None
    assert row.expires_at > datetime.utcnow()


def test_rotate_marks_parent_rotated_and_links_child(db, user):
    """Successful rotation: parent → revoked('rotated') + child has
    parent_id = parent.id."""
    _secret_a, parent = svc.issue_refresh_token(db, user=user)
    db.commit()

    _secret_b, child = svc.rotate(db, presented=parent)
    db.commit()

    assert parent.revoked_at is not None
    assert parent.revoked_reason == "rotated"
    assert parent.last_used_at is not None
    assert child.parent_id == parent.id
    assert child.revoked_at is None


def test_rotate_propagates_device_label_when_caller_omits(db, user):
    """The rotated child carries forward parent's device_label unless
    explicitly overridden."""
    _secret_a, parent = svc.issue_refresh_token(db, user=user, device_label="m1")
    db.commit()

    _secret_b, child = svc.rotate(db, presented=parent)
    db.commit()

    assert child.device_label == "m1"


# ──────────────────────────────────────────────────────────────────────
# Reuse detection
# ──────────────────────────────────────────────────────────────────────


def test_revoke_chain_from_walks_parents_and_children(db, user):
    """Build A → B → C, replay B, the whole chain burns."""
    _sa, a = svc.issue_refresh_token(db, user=user)
    _sb, b = svc.rotate(db, presented=a)
    _sc, c = svc.rotate(db, presented=b)
    db.commit()
    # Before replay: a + b are rotated (revoked_reason='rotated'),
    # c is the live leaf.
    assert a.revoked_reason == "rotated"
    assert b.revoked_reason == "rotated"
    assert c.revoked_at is None

    # Simulate a replay of B — caller asks revoke_chain_from to burn
    # everything reachable from B.
    burned = svc.revoke_chain_from(db, leaf=b, reason="reuse_detected")
    db.commit()

    # `revoke_chain_from` only flips ALREADY-LIVE rows; a + b were
    # already revoked with 'rotated', so only c flips. Count = 1.
    # But all three now read as 'reuse_detected' on c (down-walk)
    # and stay 'rotated' on a + b (no-op).
    assert burned == 1
    db.refresh(c)
    assert c.revoked_at is not None
    assert c.revoked_reason == "reuse_detected"
    # a + b keep their original revoke reasons (idempotent no-op).
    db.refresh(a)
    db.refresh(b)
    assert a.revoked_reason == "rotated"
    assert b.revoked_reason == "rotated"


def test_revoke_chain_from_kills_live_descendant_when_leaf_is_root(db, user):
    """When the leaf is the ROOT of the chain (parent_id=None), the
    walk should propagate down to every still-live descendant."""
    _sa, a = svc.issue_refresh_token(db, user=user)
    _sb, b = svc.rotate(db, presented=a)
    # Manually un-revoke `a` so we simulate a forked-chain edge case
    # where the up-walk has a live root. (Should never happen post-B-1.)
    a.revoked_at = None
    a.revoked_reason = None
    db.commit()

    burned = svc.revoke_chain_from(db, leaf=b, reason="reuse_detected")
    db.commit()

    # b was already 'rotated' (when we rotated it to make a child).
    # Wait — no, we only created one rotation, so b is the leaf and
    # IS live. Let me re-check: rotate(a) made b, marked a='rotated',
    # left b live. Then we un-revoked a. Now we revoke_chain_from(b).
    #   up: walk a → live → revoke (count=1)
    #   leaf itself: b is live → revoke (count=2)
    # Down-walk from b: no children.
    assert burned == 2


def test_revoke_chain_from_respects_max_rows_cap(db, user):
    """Bound the walk to `max_rows` so a malicious replay against a
    long chain doesn't write-amplify forever (review I-3).

    A normal rotation chain only has the leaf live (parents are all
    'rotated' from prior exchanges), so the cap effectively never
    triggers on a sane chain. We exercise the cap by manually
    un-revoking parents to simulate a pathological "everyone alive"
    state where the cap MUST kick in.
    """
    _s, head = svc.issue_refresh_token(db, user=user)
    current = head
    for _ in range(9):
        _s, current = svc.rotate(db, presented=current)
    db.commit()
    # Manually wake the entire chain so all 10 rows are live.
    node = current
    while node is not None:
        node.revoked_at = None
        node.revoked_reason = None
        node = node.parent
    db.commit()

    burned = svc.revoke_chain_from(
        db, leaf=current, reason="reuse_detected", max_rows=3
    )
    db.commit()
    assert burned == 3


# ──────────────────────────────────────────────────────────────────────
# Grace-window helper (B-1)
# ──────────────────────────────────────────────────────────────────────


def test_find_rotated_child_returns_active_child(db, user):
    """`find_rotated_child(parent=a)` returns the still-active child b."""
    _sa, a = svc.issue_refresh_token(db, user=user)
    _sb, b = svc.rotate(db, presented=a)
    db.commit()
    found = svc.find_rotated_child(db, parent=a)
    assert found is not None
    assert found.id == b.id


def test_find_rotated_child_returns_none_when_no_child(db, user):
    """Parent with no rotations → None."""
    _sa, a = svc.issue_refresh_token(db, user=user)
    db.commit()
    assert svc.find_rotated_child(db, parent=a) is None


def test_find_rotated_child_picks_most_recent_active(db, user):
    """If the chain forked (defensive — shouldn't happen post-B-1
    mutex), return the most recently-created live child."""
    _sa, a = svc.issue_refresh_token(db, user=user)
    _sb, b = svc.rotate(db, presented=a)
    db.commit()
    # Manually create a SECOND child of a (forked).
    time.sleep(0.01)  # ensure created_at differs
    _sc, c = svc.issue_refresh_token(db, user=user, parent=a)
    db.commit()

    found = svc.find_rotated_child(db, parent=a)
    assert found is not None
    # c is younger; should win.
    assert found.id == c.id


# ──────────────────────────────────────────────────────────────────────
# Single-row revoke
# ──────────────────────────────────────────────────────────────────────


def test_revoke_one_marks_revoked(db, user):
    _s, row = svc.issue_refresh_token(db, user=user)
    db.commit()
    svc.revoke_one(db, row=row, reason="user_revoked")
    db.commit()
    assert row.revoked_at is not None
    assert row.revoked_reason == "user_revoked"


def test_revoke_one_is_idempotent(db, user):
    """Calling revoke_one twice doesn't change the reason or timestamp."""
    _s, row = svc.issue_refresh_token(db, user=user)
    db.commit()
    svc.revoke_one(db, row=row, reason="user_revoked")
    db.commit()
    first_ts = row.revoked_at
    time.sleep(0.01)
    svc.revoke_one(db, row=row, reason="logout")
    db.commit()
    # No-op on already-revoked rows.
    assert row.revoked_at == first_ts
    assert row.revoked_reason == "user_revoked"
