"""SP1.5 — Luna secondary-pointer / background-control contract + security fixtures.

Executable contract for the background app-control path defined in
``docs/plans/2026-06-11-luna-secondary-pointer-background-control.md`` (Luna
APPROVE for SP1.5 fixtures only). This is the security spec SP2+ must satisfy:
pure decision logic + display-safe golden fixtures, with **no native actuation**,
no AX/CGEvent calls, and no DB. Every §11 minimum-test line and the §5.3 denial
codes get an executable assertion here, before any resolver/AX/PID code exists.

Scope: contract/security parity only. Imports the pure decision module
``app.services.desktop_background_codes`` and validates the golden fixtures under
``docs/contracts/desktop-control/``. Nothing here moves a cursor or posts input.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.desktop_background_codes import (
    AX_PRIMITIVES,
    ALLOWED_BACKGROUND_DENIAL_CODES,
    CANONICAL_BACKGROUND_REASONS,
    FORBIDDEN_EVENT_FIELDS,
    KEYBOARD_LIKE_PRIMITIVES,
    OVERLAY_ALLOWED_INTENTS,
    OVERLAY_FORBIDDEN_INTENTS,
    PID_PRIMITIVES,
    BackgroundControlDenialCode,
    BackgroundPrimitiveAction,
    TargetIdentity,
    background_code_for_reason,
    byte_free_violations,
    lease_decision,
    overlay_authority_decision,
    points_drift,
    primitive_fallback_decision,
    raw_bytes_decision,
    readback_decision,
    secure_input_background_decision,
    target_identity_decision,
    window_drift_decision,
    window_relative_points_ok,
)
from app.services.desktop_control_codes import DesktopDenialCode

# short aliases used throughout the assertions
BC = BackgroundControlDenialCode
Prim = BackgroundPrimitiveAction

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _fixtures_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "docs" / "contracts" / "desktop-control"
        if cand.is_dir():
            return cand
    raise AssertionError("docs/contracts/desktop-control not found above this test")


FIXTURES = _fixtures_dir()
CLAIM = "background_command_claim.display_safe.json"
VERIFIED = "background_control_verified.event.json"
OVERLAY = "overlay_event.subscriber_only.json"
DENY = "background_control_denied.display_safe.json"
ALL_FIXTURES = [CLAIM, VERIFIED, OVERLAY, DENY]


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# A signed-vs-observed identity pair that should ALLOW (used as the happy
# baseline; each negative test mutates exactly one field off it).
def _good_signed() -> TargetIdentity:
    return TargetIdentity(
        bundle_id="net.whatsapp.WhatsApp",
        pid=4321,
        window_id="win-abc",
        signing_id="sha256:team",
        launch_token="sha256:launch",
    )


def _good_observed() -> TargetIdentity:
    return TargetIdentity(
        bundle_id="net.whatsapp.WhatsApp",
        pid=4321,
        window_id="win-abc",
        signing_id="sha256:team",
        launch_token="sha256:launch",
    )


# ─────────────────────────────────────────────────────────────────────────────
# §5.3 — stable byte-free denial-code vocabulary
# ─────────────────────────────────────────────────────────────────────────────


def test_every_sp15_denial_code_is_display_safe_snake_case():
    # Codes are safe to emit in session_events / audit metadata: lowercase
    # snake_case tokens only — never raw screen / app / window content.
    for code in BackgroundControlDenialCode:
        v = code.value
        assert v == v.lower()
        assert " " not in v and ";" not in v and ":" not in v
        assert "/" not in v and "'" not in v
        assert set(v) <= set("abcdefghijklmnopqrstuvwxyz0123456789_")


def test_plan_5_3_codes_are_all_present():
    # The exact §5.3 set must exist (new tokens here; `stopped`/`secure_input`
    # reuse the canonical PR-C codes and live in ALLOWED_BACKGROUND_DENIAL_CODES).
    new_tokens = {
        "wrong_bundle", "stale_pid", "pid_reused", "missing_window", "bounds_drift",
        "display_drift", "title_hash_drift", "signing_identity_mismatch", "lease_lost",
        "locked", "flag_disabled", "fallback_not_allowed", "readback_failed",
        "raw_bytes_blocked", "overlay_not_authoritative",
    }
    assert {c.value for c in BackgroundControlDenialCode} == new_tokens
    # the two reused canonical codes complete the background vocabulary
    assert DesktopDenialCode.STOPPED.value in ALLOWED_BACKGROUND_DENIAL_CODES
    assert DesktopDenialCode.SECURE_INPUT_ACTIVE.value in ALLOWED_BACKGROUND_DENIAL_CODES


def test_background_reason_maps_to_exactly_one_code_and_round_trips():
    # Each canonical reason maps to its code; the bare token maps to itself too.
    for reason, code in CANONICAL_BACKGROUND_REASONS:
        assert background_code_for_reason(reason) == code
        assert background_code_for_reason(code) == code


def test_unknown_background_reason_is_unmapped():
    assert background_code_for_reason("something nobody planned for") is None
    assert background_code_for_reason("") is None
    assert background_code_for_reason(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# §11 — target identity beyond PID
# ─────────────────────────────────────────────────────────────────────────────


def test_identity_happy_path_allows():
    assert target_identity_decision(
        _good_signed(), _good_observed(), app_alive=True, signing_required=True
    ) is None


def test_identity_app_quit_is_stale_pid():
    assert target_identity_decision(
        _good_signed(), None, app_alive=False, signing_required=True
    ) == BC.STALE_PID


def test_identity_wrong_bundle_denies():
    obs = TargetIdentity("com.evil.Other", 4321, "win-abc", "sha256:team", "sha256:launch")
    assert target_identity_decision(
        _good_signed(), obs, app_alive=True, signing_required=True
    ) == BC.WRONG_BUNDLE


def test_identity_missing_window_denies():
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, None, "sha256:team", "sha256:launch")
    assert target_identity_decision(
        _good_signed(), obs, app_alive=True, signing_required=True
    ) == BC.MISSING_WINDOW


def test_identity_signing_mismatch_denies():
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:OTHER", "sha256:launch")
    assert target_identity_decision(
        _good_signed(), obs, app_alive=True, signing_required=True
    ) == BC.SIGNING_IDENTITY_MISMATCH


def test_identity_missing_signing_proof_denies_when_required():
    signed = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", None, "sha256:launch")
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", None, "sha256:launch")
    assert target_identity_decision(
        signed, obs, app_alive=True, signing_required=True
    ) == BC.SIGNING_IDENTITY_MISMATCH


def test_identity_pid_reuse_same_pid_different_proc_denies():
    # PID alone is never identity: same pid number, different launch token.
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:team", "sha256:DIFFERENT")
    assert target_identity_decision(
        _good_signed(), obs, app_alive=True, signing_required=True
    ) == BC.PID_REUSED


def test_identity_pid_without_proc_proof_denies():
    # No proc/launch identity proof at all -> cannot prove same process -> deny.
    signed = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:team", None)
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:team", None)
    assert target_identity_decision(
        signed, obs, app_alive=True, signing_required=True
    ) == BC.PID_REUSED


def test_identity_relaunch_new_pid_is_stale():
    obs = TargetIdentity("net.whatsapp.WhatsApp", 9999, "win-abc", "sha256:team", "sha256:launch")
    assert target_identity_decision(
        _good_signed(), obs, app_alive=True, signing_required=True
    ) == BC.STALE_PID


# ─────────────────────────────────────────────────────────────────────────────
# §5.2 — window drift / coordinate contract (POINTS, not pixels)
# ─────────────────────────────────────────────────────────────────────────────


def test_points_drift_is_max_abs_delta_in_points():
    assert points_drift([0, 0, 900, 700], [2, 1, 901, 700]) == 2
    assert points_drift([0, 0, 900, 700], [0, 0, 900, 700]) == 0


def test_window_drift_within_tolerance_allows():
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=[2, 1, 901, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
    ) is None


def test_window_bounds_drift_beyond_tolerance_denies():
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=[40, 0, 900, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
    ) == BC.BOUNDS_DRIFT


def test_display_drift_denies():
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=[0, 0, 900, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=2,
    ) == BC.DISPLAY_DRIFT


def test_title_hash_drift_denies_only_when_bound():
    # title binding present -> drift denies
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=[0, 0, 900, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
        signed_title_hash="sha256:a", observed_title_hash="sha256:b",
    ) == BC.TITLE_HASH_DRIFT
    # no title binding -> not checked
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=[0, 0, 900, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
        signed_title_hash=None, observed_title_hash="sha256:b",
    ) is None


def test_window_relative_points_are_integer_and_in_bounds():
    assert window_relative_points_ok({"x": 120, "y": 80}, [0, 0, 900, 700]) is True
    # outside the window
    assert window_relative_points_ok({"x": 950, "y": 80}, [0, 0, 900, 700]) is False
    # right/bottom edges are outside the half-open window-relative range.
    assert window_relative_points_ok({"x": 900, "y": 80}, [0, 0, 900, 700]) is False
    assert window_relative_points_ok({"x": 120, "y": 700}, [0, 0, 900, 700]) is False
    # floats are not points (no Retina pixel/point ambiguity allowed)
    assert window_relative_points_ok({"x": 120.5, "y": 80}, [0, 0, 900, 700]) is False
    # negative is not window-relative
    assert window_relative_points_ok({"x": -1, "y": 80}, [0, 0, 900, 700]) is False


# ─────────────────────────────────────────────────────────────────────────────
# §5.1 — lease / ownership; §11 — Stop, Lock, flag revoke, lease loss
# ─────────────────────────────────────────────────────────────────────────────


def _lease_kwargs(**over):
    base = dict(
        lease_present=True, lease_expired=False, lease_replayed=False,
        lease_consumed=False, command_id_match=True, app_alive=True,
        stop_latched=False, lock_latched=False, tenant_flag_enabled=True,
        capability_flag_enabled=True,
    )
    base.update(over)
    return base


def test_lease_active_allows():
    assert lease_decision(**_lease_kwargs()) is None


def test_stop_latched_wins_over_everything():
    # Stop must deny before every native call (§11), even if lease also lost.
    assert lease_decision(**_lease_kwargs(stop_latched=True, lease_present=False)) == DesktopDenialCode.STOPPED.value


def test_lock_latched_denies():
    assert lease_decision(**_lease_kwargs(lock_latched=True)) == BC.LOCKED


@pytest.mark.parametrize("flag", ["tenant_flag_enabled", "capability_flag_enabled"])
def test_flag_revoked_denies(flag):
    assert lease_decision(**_lease_kwargs(**{flag: False})) == BC.FLAG_DISABLED


@pytest.mark.parametrize(
    "over",
    [
        {"lease_present": False},
        {"lease_expired": True},
        {"lease_replayed": True},
        {"lease_consumed": True},
        {"command_id_match": False},
        {"app_alive": False},
    ],
)
def test_lease_loss_variants_deny(over):
    assert lease_decision(**_lease_kwargs(**over)) == BC.LEASE_LOST


# ─────────────────────────────────────────────────────────────────────────────
# §5 — independent AX vs PID primitive flags; §11 — AX approval ≠ PID fallback
# ─────────────────────────────────────────────────────────────────────────────


def _flags(**over):
    base = dict(
        ax_set_value_allowed=True, ax_press_allowed=True,
        pid_post_key_allowed=False, pid_post_click_allowed=False,
    )
    base.update(over)
    return base


def test_ax_press_allowed_when_its_flag_set():
    assert primitive_fallback_decision(Prim.AX_PRESS.value, **_flags()) is None


def test_ax_approval_does_not_authorize_pid_fallback():
    # ax_press allowed, but pid_post_click NOT allowed -> the PID fallback is denied.
    assert primitive_fallback_decision(Prim.PID_POST_CLICK.value, **_flags()) == BC.FALLBACK_NOT_ALLOWED
    assert primitive_fallback_decision(Prim.PID_POST_KEY.value, **_flags()) == BC.FALLBACK_NOT_ALLOWED


def test_disallowed_ax_primitive_is_flag_disabled():
    assert primitive_fallback_decision(
        Prim.AX_SET_VALUE.value, **_flags(ax_set_value_allowed=False)
    ) == BC.FLAG_DISABLED


def test_pid_primitive_allowed_only_with_its_own_flag():
    assert primitive_fallback_decision(
        Prim.PID_POST_CLICK.value, **_flags(pid_post_click_allowed=True)
    ) is None


def test_ax_and_pid_primitive_sets_are_disjoint():
    assert AX_PRIMITIVES.isdisjoint(PID_PRIMITIVES)
    assert AX_PRIMITIVES | PID_PRIMITIVES == {p.value for p in BackgroundPrimitiveAction}


# ─────────────────────────────────────────────────────────────────────────────
# §11 — secure input denies keyboard-like actions (even non-frontmost)
# ─────────────────────────────────────────────────────────────────────────────


def test_secure_input_blocks_text_entry_primitives():
    assert secure_input_background_decision(True, Prim.AX_SET_VALUE.value) == DesktopDenialCode.SECURE_INPUT_ACTIVE.value
    assert secure_input_background_decision(True, Prim.PID_POST_KEY.value) == DesktopDenialCode.SECURE_INPUT_ACTIVE.value


def test_secure_input_does_not_block_press_or_click():
    assert secure_input_background_decision(True, Prim.AX_PRESS.value) is None
    assert secure_input_background_decision(True, Prim.PID_POST_CLICK.value) is None


def test_secure_input_inactive_never_blocks():
    for p in BackgroundPrimitiveAction:
        assert secure_input_background_decision(False, p.value) is None


def test_keyboard_like_primitives_are_exactly_text_entry():
    assert KEYBOARD_LIKE_PRIMITIVES == {Prim.AX_SET_VALUE.value, Prim.PID_POST_KEY.value}


# ─────────────────────────────────────────────────────────────────────────────
# §8/§11 — verify-readback; AX no-op denies, PID without readback denies
# ─────────────────────────────────────────────────────────────────────────────


def test_readback_success():
    assert readback_decision(
        readback_available=True, content_hash_match=True, structural_state_ok=True
    ) is None


@pytest.mark.parametrize(
    "over",
    [
        {"readback_available": False},   # AX no-op / PID posted with no proof
        {"content_hash_match": False},   # wrong text/value
        {"structural_state_ok": False},  # field gone / not sent
    ],
)
def test_readback_failures_deny(over):
    base = dict(readback_available=True, content_hash_match=True, structural_state_ok=True)
    base.update(over)
    assert readback_decision(**base) == BC.READBACK_FAILED


# ─────────────────────────────────────────────────────────────────────────────
# §9 — overlay is subscriber-only; Stop allowed, no resume/approve/replay/extend
# ─────────────────────────────────────────────────────────────────────────────


def test_overlay_stop_request_is_allowed():
    assert overlay_authority_decision("stop_request") is None
    assert overlay_authority_decision("subscribe") is None
    assert overlay_authority_decision("hud_update") is None


@pytest.mark.parametrize(
    "intent",
    ["resume", "approve", "replay", "mutate_envelope", "extend_lease", "unlock", "issue"],
)
def test_overlay_cannot_authorize_actions(intent):
    assert overlay_authority_decision(intent) == BC.OVERLAY_NOT_AUTHORITATIVE


def test_overlay_unknown_intent_fails_closed():
    assert overlay_authority_decision("totally-unknown") == BC.OVERLAY_NOT_AUTHORITATIVE


def test_overlay_intent_sets_are_disjoint():
    assert OVERLAY_ALLOWED_INTENTS.isdisjoint(OVERLAY_FORBIDDEN_INTENTS)


# ─────────────────────────────────────────────────────────────────────────────
# §10/§11 — byte-free event shape; raw titles/labels/message text blocked
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "leaky",
    [
        {"hud": {"message_text": "hi mom"}},
        {"target": {"window_title": "Chat with Mom"}},
        {"readback": {"value": "1234 secret"}},
        {"ax_label": "Send to +1 555..."},
        {"contact_name": "Mom"},
        {"clipboard_text": "..."},
        {"screenshot": "<bytes>"},
    ],
)
def test_raw_bytes_in_event_are_blocked(leaky):
    assert byte_free_violations(leaky) != []
    assert raw_bytes_decision(leaky) == BC.RAW_BYTES_BLOCKED


def test_clean_event_has_no_violations():
    clean = {"hud": {"state": "acting", "value_chars": 11, "content_hash_match": True}}
    assert byte_free_violations(clean) == []
    assert raw_bytes_decision(clean) is None


# ─────────────────────────────────────────────────────────────────────────────
# Golden fixtures — display-safe + structural contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_fixture_is_byte_free(name):
    assert byte_free_violations(_load(name)) == [], f"{name} leaks raw/forbidden field(s)"


def test_background_claim_structure():
    c = _load(CLAIM)
    assert c["kind"] == "background_command_claim"
    assert c["capability"] == "background_control"
    # TODO(SP2): drift-check capability/risk_tier against the real service
    # constants (like test_desktop_control_contract::test_fixtures_match_service_enums)
    # once the background-control service path exists. Pinned to literals for now.
    assert c["risk_tier"] == "native_control"
    t = c["target"]
    # identity beyond PID: bundle + window id + proc/signing proof + points bounds
    for key in ("bundle_id", "window_id", "pid", "signing_team_id_hash",
                "launch_token_hash", "window_bounds", "display_id", "observed_at",
                "expires_at", "target_role"):
        assert key in t, f"claim target missing {key}"
    assert isinstance(t["pid"], int)
    assert isinstance(t["window_bounds"], list) and len(t["window_bounds"]) == 4
    assert all(isinstance(v, int) for v in t["window_bounds"]), "bounds must be integer POINTS"
    assert "window_title" not in t and t["window_title_hash"]
    # resolved primitive + independent flags
    assert c["action"]["primitive"] in {p.value for p in BackgroundPrimitiveAction}
    flags = c["primitive_flags"]
    assert set(flags) == {p.value for p in BackgroundPrimitiveAction}
    assert all(isinstance(v, bool) for v in flags.values())
    # the lease binds one window + command + capability
    lease = c["lease"]
    for key in ("lease_id", "command_id", "expires_at", "capability", "window_id"):
        assert key in lease, f"lease missing {key}"


def test_background_verified_event_is_byte_free_proof_only():
    v = _load(VERIFIED)
    assert v["kind"] == "background_control_verified"
    rb = v["readback"]
    assert rb["verified"] is True
    assert isinstance(rb["content_hash_match"], bool)
    # proof carries only hashes/counts/booleans/categories — never raw text
    assert byte_free_violations(v) == []
    assert "value" not in rb and "text" not in rb


def test_overlay_event_carries_no_authority():
    o = _load(OVERLAY)
    assert o["kind"] == "overlay_event"
    assert o["authoritative"] is False
    assert set(o["allowed_intents"]).issubset(OVERLAY_ALLOWED_INTENTS)
    # nothing the overlay claims may be an authority-granting intent
    assert set(o["allowed_intents"]).isdisjoint(OVERLAY_FORBIDDEN_INTENTS)
    for intent in o["allowed_intents"]:
        assert overlay_authority_decision(intent) is None


def test_background_deny_fixture_code_is_canonical_and_maps():
    d = _load(DENY)
    assert d["kind"] == "background_command_denied"
    assert d["status"] == "denied"
    assert d["down_channel_available"] is False
    assert d["code"] in ALLOWED_BACKGROUND_DENIAL_CODES, f"'{d['code']}' is not a background denial code"
    # the display-safe reason maps back to exactly this code
    assert background_code_for_reason(d["reason"]) == d["code"]


def test_injected_raw_field_into_claim_is_caught():
    # Mirrors the core Rust display-safe negative: a smuggled raw field is flagged.
    c = _load(CLAIM)
    c["target"]["window_title"] = "super secret window"
    assert byte_free_violations(c) != []


# ─────────────────────────────────────────────────────────────────────────────
# Review hardening (adversarial findings I-1..I-4, N-1, N-3)
# ─────────────────────────────────────────────────────────────────────────────


# I-1 / N-3 — malformed bounds must FAIL CLOSED (zip-truncation fail-open).
@pytest.mark.parametrize(
    "bad",
    [
        [0, 0],
        [],
        [0, 0, 900, 700, 1],
        [0, 0, 900, "x"],
        [0, 0, 900, 700.5],
        [0, 0, 900, True],
        [0, 0, 0, 700],
        [0, 0, 900, 0],
        [0, 0, -900, 700],
    ],
)
def test_malformed_bounds_fail_closed(bad):
    # bad as the signed side
    assert window_drift_decision(
        signed_bounds=bad, observed_bounds=[0, 0, 900, 700],
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
    ) == BC.BOUNDS_DRIFT
    # bad as the observed side
    assert window_drift_decision(
        signed_bounds=[0, 0, 900, 700], observed_bounds=bad,
        tolerance_points=4, signed_display_id=1, observed_display_id=1,
    ) == BC.BOUNDS_DRIFT


def test_window_relative_points_rejects_malformed_window_bounds():
    assert window_relative_points_ok({"x": 1, "y": 1}, [0, 0]) is False
    assert window_relative_points_ok({"x": 1, "y": 1}, []) is False
    assert window_relative_points_ok({"x": 1, "y": 1}, [0, 0, 900, "x"]) is False


# I-2 — empty-string identity proofs are morally MISSING and must deny (Inv. 6).
def test_identity_empty_window_id_denies():
    signed = TargetIdentity("net.whatsapp.WhatsApp", 4321, "", "sha256:team", "sha256:launch")
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "", "sha256:team", "sha256:launch")
    assert target_identity_decision(signed, obs, app_alive=True, signing_required=True) == BC.MISSING_WINDOW


def test_identity_empty_launch_token_is_pid_reuse():
    signed = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:team", "")
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "sha256:team", "")
    assert target_identity_decision(signed, obs, app_alive=True, signing_required=True) == BC.PID_REUSED


def test_identity_empty_signing_denies_when_required():
    signed = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "", "sha256:launch")
    obs = TargetIdentity("net.whatsapp.WhatsApp", 4321, "win-abc", "", "sha256:launch")
    assert target_identity_decision(signed, obs, app_alive=True, signing_required=True) == BC.SIGNING_IDENTITY_MISMATCH


def test_identity_empty_bundle_denies():
    signed = TargetIdentity("", 4321, "win-abc", "sha256:team", "sha256:launch")
    obs = TargetIdentity("", 4321, "win-abc", "sha256:team", "sha256:launch")
    assert target_identity_decision(signed, obs, app_alive=True, signing_required=True) == BC.WRONG_BUNDLE


# I-4 — extended WhatsApp/AX raw fields + case-insensitive key matching.
@pytest.mark.parametrize(
    "key",
    ["sender_name", "phone_number", "jid", "group_subject", "quoted_message", "caption",
     "msisdn", "last_message", "preview", "snippet", "notification_text", "message_preview",
     "accessibility_label", "placeholder", "tooltip"],
)
def test_extended_raw_fields_are_blocked(key):
    assert byte_free_violations({key: "raw content"}) != []


@pytest.mark.parametrize("key", ["AXValue", "AXTitle", "AXDescription", "Window_Title", "Message_Text"])
def test_forbidden_fields_are_case_insensitive(key):
    assert byte_free_violations({key: "raw content"}) != []


# I-3 — the byte-free guard is a structural KEY denylist BY DESIGN, not a value
# scanner (a value scanner would false-positive on hashes/categories). The real
# guarantee is emitter discipline + the typed SP2 mirror; this guard backstops the
# common "raw content under an obvious key" mistake. Documented so it is a
# conscious contract decision, not a latent surprise.
def test_byte_free_guard_is_key_only_by_design():
    assert byte_free_violations({"note": "raw message text lives here"}) == []


# N-1 — the two reused canonical codes also round-trip through the background mapper.
def test_reused_background_reasons_map_to_canonical_codes():
    assert background_code_for_reason(
        "desktop background control stopped; whatsapp_send_message denied"
    ) == DesktopDenialCode.STOPPED.value
    assert background_code_for_reason("stopped") == DesktopDenialCode.STOPPED.value
    assert background_code_for_reason(
        "desktop background control secure input; ax_set_value denied"
    ) == DesktopDenialCode.SECURE_INPUT_ACTIVE.value
    assert background_code_for_reason("secure_input_active") == DesktopDenialCode.SECURE_INPUT_ACTIVE.value
