"""Phase 2.75 / PR-C: stable desktop-control denial-code contract (pure, no DB).

These tests pin the closed denial-code enum and the pure decision helpers used by
the single-owner / pacing / secure-input / stale-approval gates. They never touch
the database, native APIs, or actuation — they only exercise display-safe code
mapping and pure decision logic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.desktop_control_codes import (
    DesktopDenialCode,
    code_for_reason,
    pacing_decision,
    secure_input_decision,
    single_owner_decision,
    stale_approval_decision,
)


def _now() -> datetime:
    return datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- reason mapping

# Every canonical display-safe reason that the API (`_safe_reason`,
# `_safe_command_reason`) or the Tauri native boundary can emit must map to
# exactly one stable code. `{action}` placeholders are filled to mimic runtime.
REASON_TO_CODE = {
    "desktop control stopped; pointer_click denied": DesktopDenialCode.STOPPED,
    "desktop control stopped; get_active_app preempted": DesktopDenialCode.STOPPED,
    "operator Stop": DesktopDenialCode.STOPPED,
    "local Stop latched": DesktopDenialCode.STOPPED,
    "desktop observe locked; get_active_app denied": DesktopDenialCode.OBSERVE_LOCKED,
    "desktop native control disabled; pointer_click denied": DesktopDenialCode.NATIVE_CONTROL_DISABLED,
    "desktop native control tier disabled; pointer_move denied": DesktopDenialCode.NATIVE_CONTROL_TIER_DISABLED,
    "desktop native control action unsupported; frobnicate denied": DesktopDenialCode.NATIVE_CONTROL_ACTION_UNSUPPORTED,
    "desktop permission readiness missing; keyboard_type denied": DesktopDenialCode.PERMISSION_NOT_READY,
    "desktop permission readiness stale; pointer_click denied": DesktopDenialCode.PERMISSION_NOT_READY,
    "desktop permission readiness not granted; pointer_move denied": DesktopDenialCode.PERMISSION_NOT_READY,
    "desktop observation permission 'screen_recording' is denied; capture_screenshot denied": DesktopDenialCode.OBSERVATION_PERMISSION_DENIED,
    "desktop observation permission denied; get_active_app denied": DesktopDenialCode.OBSERVATION_PERMISSION_DENIED,
    "desktop observation denied; capture_screenshot denied": DesktopDenialCode.OBSERVATION_DENIED,
    "desktop observation denied": DesktopDenialCode.OBSERVATION_DENIED,
    "desktop observation failed": DesktopDenialCode.OBSERVATION_FAILED,
    "desktop observation down-channel unavailable; get_active_app request denied": DesktopDenialCode.DOWN_CHANNEL_UNAVAILABLE,
    "desktop shell cannot observe; get_active_app request denied": DesktopDenialCode.SHELL_CANNOT_OBSERVE,
    "desktop command envelope missing": DesktopDenialCode.ENVELOPE_MISSING,
    "desktop command envelope required; pointer_click denied": DesktopDenialCode.ENVELOPE_REQUIRED,
    "desktop command envelope unsigned; pointer_click denied": DesktopDenialCode.ENVELOPE_UNSIGNED,
    "desktop command envelope nonce missing": DesktopDenialCode.ENVELOPE_NONCE_MISSING,
    "desktop command envelope nonce mismatch": DesktopDenialCode.ENVELOPE_NONCE_MISMATCH,
    "desktop command envelope signature invalid": DesktopDenialCode.ENVELOPE_SIGNATURE_INVALID,
    "desktop command envelope public key invalid": DesktopDenialCode.ENVELOPE_PUBLIC_KEY_INVALID,
    "desktop command envelope public key missing": DesktopDenialCode.ENVELOPE_PUBLIC_KEY_INVALID,
    "desktop command envelope key unknown": DesktopDenialCode.ENVELOPE_KEY_UNKNOWN,
    "desktop command envelope key registry invalid": DesktopDenialCode.ENVELOPE_KEY_REGISTRY_INVALID,
    "desktop command envelope expired": DesktopDenialCode.ENVELOPE_EXPIRED,
    "desktop command envelope expired; pointer_move denied": DesktopDenialCode.ENVELOPE_EXPIRED,
    "desktop command envelope binding mismatch": DesktopDenialCode.ENVELOPE_BINDING_MISMATCH,
    "desktop command envelope policy unsupported; pointer_click denied": DesktopDenialCode.ENVELOPE_POLICY_UNSUPPORTED,
    "desktop command envelope replay denied": DesktopDenialCode.ENVELOPE_REPLAYED,
    "desktop command envelope replayed": DesktopDenialCode.ENVELOPE_REPLAYED,
    "desktop command claim required; pointer_click denied": DesktopDenialCode.CLAIM_REQUIRED,
    "desktop command lease expired": DesktopDenialCode.LEASE_EXPIRED,
    "desktop command pending ttl expired": DesktopDenialCode.PENDING_TTL_EXPIRED,
    "desktop command preempted": DesktopDenialCode.PREEMPTED,
    "desktop command approval grant missing": DesktopDenialCode.APPROVAL_MISSING,
    "desktop command approval grant expired": DesktopDenialCode.APPROVAL_EXPIRED,
    "desktop command approval grant revoked": DesktopDenialCode.APPROVAL_REVOKED,
    "desktop command approval grant exhausted": DesktopDenialCode.APPROVAL_EXHAUSTED,
    "desktop command approval grant binding mismatch": DesktopDenialCode.APPROVAL_BINDING_MISMATCH,
    "desktop command approval grant replay denied": DesktopDenialCode.APPROVAL_REPLAY_DENIED,
    "desktop command target not allowlisted": DesktopDenialCode.TARGET_NOT_ALLOWLISTED,
    "active_app_drift": DesktopDenialCode.ACTIVE_APP_DRIFT,
    "target_drift": DesktopDenialCode.TARGET_DRIFT,
    "secure_input_active": DesktopDenialCode.SECURE_INPUT_ACTIVE,
    "actuation_owner_conflict": DesktopDenialCode.ACTUATION_OWNER_CONFLICT,
    "rate_capped": DesktopDenialCode.RATE_CAPPED,
    "desktop command denied": DesktopDenialCode.COMMAND_DENIED,
    "desktop command failed": DesktopDenialCode.COMMAND_FAILED,
}


@pytest.mark.parametrize("reason,expected", list(REASON_TO_CODE.items()))
def test_code_for_reason_maps_canonical_reason_to_exactly_one_code(reason, expected):
    assert code_for_reason(reason) is expected


def test_unknown_and_empty_reasons_map_to_unspecified():
    assert code_for_reason("something nobody planned for") is DesktopDenialCode.UNSPECIFIED
    assert code_for_reason("") is DesktopDenialCode.UNSPECIFIED
    assert code_for_reason(None) is DesktopDenialCode.UNSPECIFIED


def test_active_app_drift_and_target_drift_are_distinct_codes():
    assert DesktopDenialCode.ACTIVE_APP_DRIFT is not DesktopDenialCode.TARGET_DRIFT
    assert code_for_reason("active_app_drift") is not code_for_reason("target_drift")


def test_every_code_value_is_a_display_safe_token():
    # Stable codes must be lowercase snake_case tokens — never raw screen/app
    # content, no spaces, colons, semicolons, or path/title characters.
    for code in DesktopDenialCode:
        value = code.value
        assert value == value.lower()
        assert " " not in value and ";" not in value and ":" not in value
        assert "/" not in value and "'" not in value
        assert set(value) <= set("abcdefghijklmnopqrstuvwxyz0123456789_")


def test_no_canonical_reason_falls_through_to_unspecified():
    # Guards PR-C exit #1: every boundary denial maps to a concrete stable code.
    for reason in REASON_TO_CODE:
        assert code_for_reason(reason) is not DesktopDenialCode.UNSPECIFIED


# ------------------------------------------------------------- secure input gate


def test_secure_input_blocks_keyboard_only():
    assert secure_input_decision(True, "keyboard_control") is DesktopDenialCode.SECURE_INPUT_ACTIVE


def test_secure_input_does_not_block_pointer():
    assert secure_input_decision(True, "pointer_control") is None


def test_secure_input_inactive_never_blocks():
    assert secure_input_decision(False, "keyboard_control") is None
    assert secure_input_decision(False, "pointer_control") is None


# ----------------------------------------------------------------- pacing gate


def test_pacing_denies_when_inside_min_interval():
    assert pacing_decision(1000, 1100, 200) is DesktopDenialCode.RATE_CAPPED


def test_pacing_allows_after_min_interval():
    assert pacing_decision(1000, 1300, 200) is None


def test_pacing_allows_first_action_with_no_prior():
    assert pacing_decision(None, 1300, 200) is None


# -------------------------------------------------------------- single owner gate


def test_single_owner_conflict_when_another_shell_owns():
    assert single_owner_decision("desktop-aaa", "desktop-bbb") is DesktopDenialCode.ACTUATION_OWNER_CONFLICT


def test_single_owner_allows_same_owner():
    assert single_owner_decision("desktop-aaa", "desktop-aaa") is None


def test_single_owner_allows_when_unowned():
    assert single_owner_decision(None, "desktop-aaa") is None


# ------------------------------------------------------------ stale approval gate


def test_stale_approval_revoked():
    assert (
        stale_approval_decision("revoked", _now() + timedelta(minutes=5), _now(), 1)
        is DesktopDenialCode.APPROVAL_REVOKED
    )


def test_stale_approval_expired_by_time():
    assert (
        stale_approval_decision("active", _now() - timedelta(seconds=1), _now(), 1)
        is DesktopDenialCode.APPROVAL_EXPIRED
    )


def test_stale_approval_exhausted_when_no_actions_left():
    assert (
        stale_approval_decision("active", _now() + timedelta(minutes=5), _now(), 0)
        is DesktopDenialCode.APPROVAL_EXHAUSTED
    )


def test_stale_approval_active_grant_is_allowed():
    assert (
        stale_approval_decision("active", _now() + timedelta(minutes=5), _now(), 1)
        is None
    )


# ------------------------------------------------------- display-safe wiring guard


def test_denial_code_is_an_allowlisted_display_safe_metadata_key():
    from app.services.desktop_control_service import _SAFE_METADATA_KEYS

    assert "denial_code" in _SAFE_METADATA_KEYS
