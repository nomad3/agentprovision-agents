"""Unit tests for the Teams service security gates.

Covers the allowlist enforcement helper (the critical fix from PR #241
review): inbound auto-replies in `monitor_tick` MUST be filtered against
`acct.allow_from` / `acct.dm_policy`. The V1 of the service persisted
the allowlist but never read it.
"""
from app.services.teams_service import TeamsService


class _Acct:
    def __init__(self, dm_policy="allowlist", allow_from=None):
        self.dm_policy = dm_policy
        self.allow_from = allow_from or []


def test_allowlist_blocks_unknown_sender():
    acct = _Acct(dm_policy="allowlist", allow_from=["alice@corp.com"])
    assert TeamsService._is_sender_allowed(acct, "user-id-bob", "bob@corp.com") is False


def test_allowlist_passes_listed_upn():
    acct = _Acct(dm_policy="allowlist", allow_from=["alice@corp.com"])
    assert TeamsService._is_sender_allowed(acct, "user-id-alice", "alice@corp.com") is True


def test_allowlist_passes_listed_user_id():
    acct = _Acct(dm_policy="allowlist", allow_from=["user-id-alice"])
    assert TeamsService._is_sender_allowed(acct, "user-id-alice", "") is True


def test_allowlist_case_insensitive_upn():
    """UPNs are case-insensitive in Microsoft Graph; allowlist must match
    that. The V1 helper would have rejected a tenant whose admin typed
    `Alice@CORP.com` even when the user's actual UPN matched."""
    acct = _Acct(dm_policy="allowlist", allow_from=["Alice@CORP.com"])
    assert TeamsService._is_sender_allowed(acct, "x", "alice@corp.com") is True


def test_open_policy_passes_anyone():
    acct = _Acct(dm_policy="open", allow_from=[])
    assert TeamsService._is_sender_allowed(acct, "x", "anyone@anywhere.com") is True


def test_star_wildcard_in_allowlist_passes_anyone():
    """The route layer normalizes ``dm_policy="open"`` by prepending ``*``.
    The gate honors that wildcard."""
    acct = _Acct(dm_policy="allowlist", allow_from=["*"])
    assert TeamsService._is_sender_allowed(acct, "x", "anyone@anywhere.com") is True


def test_empty_allowlist_blocks_everyone():
    acct = _Acct(dm_policy="allowlist", allow_from=[])
    assert TeamsService._is_sender_allowed(acct, "x", "anyone@anywhere.com") is False


def test_unknown_dm_policy_defaults_to_allowlist():
    """A null/missing dm_policy must NOT fail open. The default is the
    safer "allowlist" semantics."""
    acct = _Acct(dm_policy=None, allow_from=[])
    assert TeamsService._is_sender_allowed(acct, "x", "anyone@anywhere.com") is False
