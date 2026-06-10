"""Phase 5 P5.1 — the signed actuation-args normalizer.

``_normalize_native_control_args`` validates the action-specific coords/text/keys
that get SIGNED into the command envelope, so the client actuates exactly what the
server authorized (never a client-chosen or on-screen-derived value). Pure logic.
"""
import json

import pytest

from app.services.desktop_control_service import _canonical_json
from app.services.desktop_control_service import _envelope_target_payload
from app.services.desktop_control_service import _normalize_native_control_args as norm
from app.services.desktop_control_service import (
    _normalize_native_control_target_binding as norm_target,
)
from app.services.desktop_control_service import _validate_signed_actuation_args as vsa


def test_pointer_args_normalized_to_integer_micro_units():
    # Coords are signed as integer micro-units (0..1_000_000), NOT floats, so the
    # signed payload is byte-stable across the Python signer and the Rust verifier.
    assert norm("pointer_move", {"x": 0.3, "y": 0.4}) == {"x": 300000, "y": 400000}
    assert norm("pointer_click", {"x": 0.0, "y": 1.0}) == {"x": 0, "y": 1_000_000}
    # The output values are Python ints (json.dumps emits "300000", no decimal).
    out = norm("pointer_move", {"x": 0.7, "y": 0.123456})
    assert isinstance(out["x"], int) and isinstance(out["y"], int)
    assert out == {"x": 700000, "y": 123456}


def test_pointer_args_none_is_canary_compatible():
    # canary commands carry no args -> None (unchanged envelope)
    assert norm("pointer_move", None) is None
    assert norm("pointer_click", None) is None


@pytest.mark.parametrize("bad", [{"x": 1.5, "y": 0.5}, {"x": -0.1, "y": 0.5}, {"x": "a", "y": 0.5}, {"y": 0.5}])
def test_pointer_args_out_of_range_rejected(bad):
    with pytest.raises(ValueError):
        norm("pointer_move", bad)


def test_keyboard_type_text_bounded():
    assert norm("keyboard_type", {"text": "hello luna"}) == {"text": "hello luna"}


@pytest.mark.parametrize(
    "bad",
    [{"text": ""}, {"text": "x" * 257}, {"text": 5}, {}, {"text": "hi\x00there"}, {"text": "a\nb"}],
)
def test_keyboard_type_invalid_rejected(bad):
    # incl. control characters (null, newline) — no injection of control bytes
    with pytest.raises(ValueError):
        norm("keyboard_type", bad)


def test_keyboard_chord_allowlisted_normalized():
    # only the safe-chord set (arrows + shift+arrows) is accepted
    assert norm("keyboard_key_chord", {"keys": ["Left"]}) == {"keys": ["left"]}
    assert norm("keyboard_key_chord", {"keys": ["Shift", "Right"]}) == {"keys": ["shift", "right"]}
    # aliases fold to the CANONICAL token in the signed keys (arrowup→up)
    assert norm("keyboard_key_chord", {"keys": ["ArrowUp"]}) == {"keys": ["up"]}


@pytest.mark.parametrize(
    "bad",
    [
        {"keys": []},
        {"keys": ["a"] * 6},
        {"keys": "a"},
        {"keys": [1]},
        {"keys": ["cmd shift"]},  # space -> not a single token
        {"keys": ["thiskeyiswaytoolong"]},  # > 16 chars
        {"keys": ["a", "b;rm -rf"]},  # injection-y string
        {"keys": ["cmd", "a"]},  # not in the safe-chord allowlist
        {"keys": ["shift", "x"]},  # shift+x not allowed
        {"keys": ["a"]},  # bare 'a' is not an arrow
        {"keys": ["shift"]},  # modifier only, no main key
    ],
)
def test_keyboard_chord_invalid_rejected(bad):
    with pytest.raises(ValueError):
        norm("keyboard_key_chord", bad)


def test_unknown_action_carries_no_args():
    assert norm("pointer_scroll", {"x": 0.5}) is None
    assert norm("capture_screenshot", {"foo": "bar"}) is None


# ── _validate_signed_actuation_args: the build-path re-validator ──────────────
# It must be IDEMPOTENT on already-normalized args (the normalizer is not, for
# pointer), so the envelope-build step never re-converts persisted micro-units.


@pytest.mark.parametrize(
    "action,raw",
    [
        ("pointer_move", {"x": 0.3, "y": 0.4}),
        ("pointer_click", {"x": 0.0, "y": 1.0}),
        ("pointer_move", {"x": 1e-6, "y": 1.0}),
        ("keyboard_type", {"text": "hi simon"}),
        ("keyboard_key_chord", {"keys": ["Shift", "Left"]}),
    ],
)
def test_validate_is_idempotent_on_normalized_args(action, raw):
    # validate(normalize(fraction)) == normalize(fraction) — the build re-validation
    # of the persisted form returns it unchanged (this is the bug the BLOCKER fixed:
    # the old build path re-ran normalize and rejected/garbled the micro-units).
    normalized = norm(action, raw)
    assert vsa(action, normalized) == normalized


def test_validate_none_is_none():
    assert vsa("pointer_move", None) is None
    assert vsa("keyboard_type", None) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"x": 0.3, "y": 0.4},  # floats are NOT valid persisted micro-units
        {"x": 300000},  # missing y
        {"x": 1000001, "y": 0},  # out of micro-unit range
        {"x": -1, "y": 0},
        {"x": True, "y": 0},  # bool is not a coord
        {"x": "300000", "y": 0},  # string is not an int
    ],
)
def test_validate_rejects_malformed_persisted_pointer_args(bad):
    with pytest.raises(ValueError):
        vsa("pointer_move", bad)


# ── target_binding.bounds: integer canonicalization (cross-language signature) ──
# bounds rides INTO the Ed25519-signed envelope (via _envelope_target_payload). It
# must serialize byte-identically Python↔Rust or the client silently fails the
# signature. Floats diverge (CPython repr vs Rust ryu); integers do not — so the
# normalizer quantizes bounds to int. (Same class as the pointer micro-unit fix.)


def test_target_bounds_quantized_to_int():
    t = norm_target(
        {"bundle_id": "com.apple.TextEdit", "action": "pointer_click",
         "bounds": [120.7, 80.2, 800.0, 600.9]},
        action="pointer_click",
    )
    assert t["bounds"] == [121, 80, 800, 601]
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in t["bounds"])


def test_target_bounds_canonical_json_has_integer_literals():
    from datetime import datetime, timezone

    t = norm_target(
        {"bundle_id": "com.apple.TextEdit", "action": "pointer_click",
         "bounds": [120.0, 80.0, 800.0, 600.0]},
        action="pointer_click",
    )
    payload = _envelope_target_payload(t, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    blob = _canonical_json(payload).decode()
    # integer literals only — no float repr (".0") would reach the signed bytes
    assert '"bounds":[120,80,800,600]' in blob
    assert "120.0" not in blob and "800.0" not in blob
    # and the canonical bytes round-trip to ints (what the Rust verifier re-serializes)
    assert json.loads(blob)["bounds"] == [120, 80, 800, 600]


@pytest.mark.parametrize(
    "bad_bounds",
    [
        [float("nan"), 0, 0, 0],      # non-finite would emit invalid `NaN` JSON
        [float("inf"), 0, 0, 0],      # non-finite would emit `Infinity`
        [1, 2, 3],                    # wrong arity
        [True, 1, 2, 3],              # bool is not a coord
        "120,80,800,600",            # not a list
    ],
)
def test_target_bounds_invalid_dropped(bad_bounds):
    t = norm_target(
        {"bundle_id": "com.apple.TextEdit", "action": "pointer_click", "bounds": bad_bounds},
        action="pointer_click",
    )
    # invalid bounds is dropped (fail-closed), never carried as a divergent value
    assert "bounds" not in t


# ── keyboard SEND key (enter) — the "type a message + send" enabler ──────────


def test_keyboard_chord_enter_send_key_accepted():
    # bare enter is allowlisted (the send/submit key); 'return' folds to enter
    assert norm("keyboard_key_chord", {"keys": ["enter"]}) == {"keys": ["enter"]}
    # the 'return' alias folds to the canonical 'enter' in the signed keys
    assert norm("keyboard_key_chord", {"keys": ["Return"]}) == {"keys": ["enter"]}


@pytest.mark.parametrize("bad", [["shift", "enter"], ["cmd", "enter"], ["enter", "left"]])
def test_keyboard_chord_enter_with_modifier_or_extra_key_rejected(bad):
    # ONLY bare enter is allowed — shift+enter (newline), cmd+enter, and multi-key
    # chords are not in the safe-chord allowlist.
    with pytest.raises(ValueError):
        norm("keyboard_key_chord", {"keys": bad})
