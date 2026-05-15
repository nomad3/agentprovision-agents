"""Regression test for the refresh-token-preserve bug in
`_update_stored_tokens` (`apps/api/app/api/v1/oauth.py`).

Original bug:
  Google does not rotate `refresh_token` on every refresh — most
  refresh responses contain only `access_token` + `expires_in`. The
  helper revoked BOTH `oauth_token` AND `refresh_token` rows
  unconditionally, then stored the new `access_token` and skipped the
  `refresh_token` store when the param was None. Net: the very first
  successful refresh after initial consent destroyed the long-lived
  refresh_token, leaving the tenant with a credential that could
  never be refreshed again — Luna would eventually say "token
  expired" with no recovery path short of re-consenting.

Tests lock both branches:
  1. refresh response WITHOUT refresh_token → existing refresh_token
     stays active (Google's normal case).
  2. refresh response WITH refresh_token → existing refresh_token is
     revoked + replaced (Microsoft refresh-token-rotation case).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from sqlalchemy.sql.elements import BindParameter

from app.api.v1 import oauth as oauth_module


def _make_active_credential(credential_key: str) -> MagicMock:
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.credential_key = credential_key
    cred.status = "active"
    return cred


def _extract_in_clause_values(filter_call_args) -> set:
    """Walk a SQLAlchemy filter() args tuple to find the credential_key
    IN-clause and return its expanding bind-parameter values."""
    for arg in filter_call_args:
        # IN clauses produce a BinaryExpression whose `right` is an
        # expanding BindParameter with `.value` set to the input list.
        right = getattr(arg, "right", None)
        if isinstance(right, BindParameter):
            value = getattr(right, "value", None)
            if isinstance(value, (list, tuple)) and value and all(
                isinstance(v, str) for v in value
            ):
                return set(value)
    return set()


def _wire_db_chain_filtering_by_credential_key(query_rows: list) -> MagicMock:
    """Build a `db` mock whose `.query().filter().all()` chain
    inspects the filter() args, extracts the credential_key IN-list,
    and returns only the subset of `query_rows` whose key matches.

    This way the test exercises the actual narrowing logic the fix
    introduces: when the IN-list contains only 'oauth_token', a
    refresh_token row in `query_rows` is NOT returned (and thus NOT
    revoked).
    """
    db = MagicMock()
    chain = MagicMock()

    def filter_side_effect(*args, **_kwargs):
        keys = _extract_in_clause_values(args)
        if keys:
            chain.all.return_value = [
                r for r in query_rows if r.credential_key in keys
            ]
        else:
            chain.all.return_value = list(query_rows)
        return chain

    chain.filter.side_effect = filter_side_effect
    db.query.return_value = chain
    db._chain = chain  # attached for inspection
    return db


def test_refresh_without_new_refresh_token_preserves_existing(monkeypatch):
    """Google case: refresh response has only `access_token`. The fix
    narrows the IN-list to `['oauth_token']`, so only the
    oauth_token row is revoked. The refresh_token row stays active
    and the next refresh can still mint new access_tokens.

    BEFORE THE FIX: IN-list was `['oauth_token', 'refresh_token']`,
    so the chain returned the refresh_token row too, and the loop
    revoked it — destroying the only path to future refreshes.
    """
    existing_oauth = _make_active_credential("oauth_token")
    existing_refresh = _make_active_credential("refresh_token")
    db = _wire_db_chain_filtering_by_credential_key(
        [existing_oauth, existing_refresh]
    )

    revoked: list = []
    stored: list = []
    monkeypatch.setattr(
        oauth_module,
        "revoke_credential",
        lambda db, credential_id, tenant_id: revoked.append(credential_id),
    )
    monkeypatch.setattr(
        oauth_module,
        "store_credential",
        lambda *args, **kwargs: stored.append(kwargs),
    )

    oauth_module._update_stored_tokens(
        db,
        integration_config_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        access_token="new-access-token",
        refresh_token=None,
    )

    # The IN-list must contain ONLY oauth_token (regression guard).
    in_keys = _extract_in_clause_values(db._chain.filter.call_args.args)
    assert in_keys == {"oauth_token"}, (
        f"BUG REGRESSION: revoke-filter included {in_keys}. "
        "When the refresh response has no refresh_token, the IN-list "
        "must be limited to 'oauth_token' so the existing "
        "refresh_token row is preserved for future refreshes."
    )

    # Side-effect verification: only oauth_token revoked, only
    # oauth_token stored.
    assert existing_oauth.id in revoked
    assert existing_refresh.id not in revoked
    assert len(stored) == 1
    assert stored[0]["credential_key"] == "oauth_token"
    assert stored[0]["plaintext_value"] == "new-access-token"


def test_refresh_with_rotated_refresh_token_swaps_both(monkeypatch):
    """Microsoft rotation case: refresh response carries a new
    `refresh_token`. Both old rows revoked, both new rows stored —
    rotation invariant preserved so the old refresh_token can't be
    reused after rotation.
    """
    existing_oauth = _make_active_credential("oauth_token")
    existing_refresh = _make_active_credential("refresh_token")
    db = _wire_db_chain_filtering_by_credential_key(
        [existing_oauth, existing_refresh]
    )

    revoked: list = []
    stored: list = []
    monkeypatch.setattr(
        oauth_module,
        "revoke_credential",
        lambda db, credential_id, tenant_id: revoked.append(credential_id),
    )
    monkeypatch.setattr(
        oauth_module,
        "store_credential",
        lambda *args, **kwargs: stored.append(kwargs),
    )

    oauth_module._update_stored_tokens(
        db,
        integration_config_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        access_token="new-access-token",
        refresh_token="rotated-refresh-token",
    )

    in_keys = _extract_in_clause_values(db._chain.filter.call_args.args)
    assert in_keys == {"oauth_token", "refresh_token"}

    assert existing_oauth.id in revoked
    assert existing_refresh.id in revoked

    stored_keys = sorted(s["credential_key"] for s in stored)
    assert stored_keys == ["oauth_token", "refresh_token"]
    stored_values = {s["credential_key"]: s["plaintext_value"] for s in stored}
    assert stored_values["oauth_token"] == "new-access-token"
    assert stored_values["refresh_token"] == "rotated-refresh-token"


def test_update_swallows_db_exceptions(monkeypatch):
    """The function logs and swallows exceptions so a refresh failure
    doesn't crash the `/internal/token` endpoint."""
    db = MagicMock()
    db.query.side_effect = RuntimeError("db broke")
    monkeypatch.setattr(
        oauth_module,
        "revoke_credential",
        lambda db, credential_id, tenant_id: None,
    )
    monkeypatch.setattr(
        oauth_module,
        "store_credential",
        lambda **kwargs: None,
    )

    # Must not raise.
    oauth_module._update_stored_tokens(
        db,
        integration_config_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        access_token="new-access-token",
        refresh_token=None,
    )
