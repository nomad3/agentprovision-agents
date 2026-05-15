"""Tests for migration 133 — `session_events` table.

Verified at three levels:
  1. Expected columns + types + indexes + constraints exist.
  2. UNIQUE(session_id, seq_no) enforcement (regression: if the
     constraint drops, replay dedup breaks).
  3. ON DELETE CASCADE from chat_sessions cleans up dependent rows
     so we don't leak event log when a session is deleted.

Convention matches `test_086_extend_conversation_episodes.py` —
direct engine + raw SQL, no ORM dependency on the model file.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def engine():
    return create_engine(os.environ["DATABASE_URL"])


def test_table_exists_with_expected_columns(engine):
    """session_events has the design's columns + types."""
    cols = {c["name"]: c for c in inspect(engine).get_columns("session_events")}
    assert "id" in cols
    assert "session_id" in cols
    assert "tenant_id" in cols
    assert "seq_no" in cols
    assert "event_type" in cols
    assert "payload" in cols
    assert "created_at" in cols
    # Type spot-checks via PG catalog
    with engine.connect() as c:
        types = {
            row[0]: row[1]
            for row in c.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'session_events' ORDER BY ordinal_position"
            ))
        }
    assert types["id"] == "uuid"
    assert types["session_id"] == "uuid"
    assert types["seq_no"] == "bigint"
    assert types["payload"] == "jsonb"
    assert types["created_at"] == "timestamp with time zone"


def test_required_indexes_present(engine):
    """Two non-unique indexes for replay + filter paths, plus the
    UNIQUE constraint that doubles as the (session_id, seq_no) index."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'session_events'"
        )).fetchall()
    names = {r[0] for r in rows}
    assert "idx_session_events_tenant_created" in names
    assert "idx_session_events_session_type" in names
    assert "session_events_session_seq_unique" in names


def test_unique_session_seq_constraint_enforced(engine):
    """Inserting a duplicate (session_id, seq_no) pair raises.

    Safety net behind the advisory-lock seq_no allocator. If this
    constraint silently drops, replay returns duplicates.
    """
    sid = uuid.uuid4()
    tid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO chat_sessions (id, source) VALUES (:id, 'test')"
        ), {"id": sid})
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO session_events (session_id, tenant_id, seq_no, event_type, payload) "
            "VALUES (:sid, :tid, 1, 'chat_message', '{}'::jsonb)"
        ), {"sid": sid, "tid": tid})

    with pytest.raises(Exception) as exc:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO session_events (session_id, tenant_id, seq_no, event_type, payload) "
                "VALUES (:sid, :tid, 1, 'chat_message', '{}'::jsonb)"
            ), {"sid": sid, "tid": tid})
    msg = str(exc.value).lower()
    assert "session_events_session_seq_unique" in msg or "duplicate" in msg

    # Cleanup
    with engine.begin() as c:
        c.execute(text("DELETE FROM chat_sessions WHERE id = :id"), {"id": sid})


def test_cascade_delete_from_chat_sessions(engine):
    """Deleting a chat_session cascades session_events rows."""
    sid = uuid.uuid4()
    tid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO chat_sessions (id, source) VALUES (:id, 'test')"
        ), {"id": sid})
        for seq in range(1, 4):
            c.execute(text(
                "INSERT INTO session_events (session_id, tenant_id, seq_no, event_type, payload) "
                "VALUES (:sid, :tid, :seq, 'chat_message', '{}'::jsonb)"
            ), {"sid": sid, "tid": tid, "seq": seq})

    with engine.connect() as c:
        count = c.execute(text(
            "SELECT COUNT(*) FROM session_events WHERE session_id = :sid"
        ), {"sid": sid}).scalar()
    assert count == 3

    with engine.begin() as c:
        c.execute(text("DELETE FROM chat_sessions WHERE id = :id"), {"id": sid})

    with engine.connect() as c:
        count_after = c.execute(text(
            "SELECT COUNT(*) FROM session_events WHERE session_id = :sid"
        ), {"sid": sid}).scalar()
    assert count_after == 0, "ON DELETE CASCADE didn't fire — session_events leaked"


def test_orm_model_round_trip(engine):
    """Model file imports cleanly + the ORM can insert/read a row.

    This catches a class of bugs where the model declares a column
    that doesn't match the migration (typo, wrong type) — the round-trip
    would fail with a mapping error.
    """
    from uuid import uuid4
    from sqlalchemy.orm import sessionmaker
    from app.models.session_event import SessionEvent

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        sid = uuid4()
        tid = uuid4()
        # Set up a chat_session for FK
        db.execute(text(
            "INSERT INTO chat_sessions (id, source) VALUES (:id, 'test')"
        ), {"id": sid})
        evt = SessionEvent(
            session_id=sid, tenant_id=tid, seq_no=1,
            event_type="chat_message", payload={"role": "user", "text": "hi"},
        )
        db.add(evt)
        db.commit()

        round_trip = db.query(SessionEvent).filter_by(session_id=sid).first()
        assert round_trip is not None
        assert round_trip.seq_no == 1
        assert round_trip.event_type == "chat_message"
        assert round_trip.payload == {"role": "user", "text": "hi"}
    finally:
        db.execute(text("DELETE FROM chat_sessions WHERE id = :id"), {"id": sid})
        db.commit()
        db.close()
