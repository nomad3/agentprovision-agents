"""Tests for coalition replay endpoint helpers (Tier 5)."""
import uuid
from datetime import datetime

from app.api.v1.insights_coalition_replay import (
    CoalitionListResponse,
    CoalitionReplayResponse,
    CoalitionSummary,
    ReplayEntry,
    _decode_cursor,
    _encode_cursor,
    _EVIDENCE_CAP_BYTES,
)


def test_summary_no_tenant_id_leak():
    fields = (CoalitionSummary.model_fields if hasattr(CoalitionSummary, 'model_fields')
              else CoalitionSummary.__fields__)
    assert 'tenant_id' not in fields
    # Includes the aggregates the UI needs
    assert {'entry_count', 'distinct_agents'}.issubset(fields.keys())


def test_replay_entry_no_blackboard_id_leak():
    """The entry-level schema includes its own id + parent links but
    NOT the parent blackboard_id (caller already knows which board)."""
    fields = (ReplayEntry.model_fields if hasattr(ReplayEntry, 'model_fields')
              else ReplayEntry.__fields__)
    assert 'blackboard_id' not in fields
    assert 'tenant_id' not in fields


def test_list_response_no_pagination_total():
    fields = (CoalitionListResponse.model_fields if hasattr(CoalitionListResponse, 'model_fields')
              else CoalitionListResponse.__fields__)
    forbidden = {'total', 'offset', 'page', 'tenant_id'}
    assert forbidden.isdisjoint(fields.keys())


def test_cursor_round_trip():
    ts = datetime(2026, 5, 3, 12, 0, 0)
    aid = uuid.uuid4()
    encoded = _encode_cursor(ts, aid)
    decoded = _decode_cursor(encoded)
    assert decoded == (ts, aid)


def test_cursor_decodes_garbage_to_none():
    for bad in ['', 'broken', 'a|b', None, 'no-pipe']:
        assert _decode_cursor(bad) is None


def test_evidence_cap_constant_is_reasonable():
    """50KB per row keeps replay payloads bounded for boards with
    huge evidence blobs but allows typical evidence (URLs, snippets,
    citations) to pass through unmolested."""
    assert 1000 < _EVIDENCE_CAP_BYTES < 1_000_000
