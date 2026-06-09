"""Phase 5 P5.1 — the signed actuation-args normalizer.

``_normalize_native_control_args`` validates the action-specific coords/text/keys
that get SIGNED into the command envelope, so the client actuates exactly what the
server authorized (never a client-chosen or on-screen-derived value). Pure logic.
"""
import pytest

from app.services.desktop_control_service import _normalize_native_control_args as norm


def test_pointer_args_normalized():
    assert norm("pointer_move", {"x": 0.3, "y": 0.4}) == {"x": 0.3, "y": 0.4}
    assert norm("pointer_click", {"x": 0.0, "y": 1.0}) == {"x": 0.0, "y": 1.0}


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


@pytest.mark.parametrize("bad", [{"text": ""}, {"text": "x" * 257}, {"text": 5}, {}])
def test_keyboard_type_invalid_rejected(bad):
    with pytest.raises(ValueError):
        norm("keyboard_type", bad)


def test_keyboard_chord_normalized():
    assert norm("keyboard_key_chord", {"keys": ["Cmd", "A"]}) == {"keys": ["cmd", "a"]}


@pytest.mark.parametrize("bad", [{"keys": []}, {"keys": ["a"] * 6}, {"keys": "a"}, {"keys": [1]}])
def test_keyboard_chord_invalid_rejected(bad):
    with pytest.raises(ValueError):
        norm("keyboard_key_chord", bad)


def test_unknown_action_carries_no_args():
    assert norm("pointer_scroll", {"x": 0.5}) is None
    assert norm("capture_screenshot", {"foo": "bar"}) is None
