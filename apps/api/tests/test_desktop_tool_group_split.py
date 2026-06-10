"""PR4d — Luna macOS computer-use agent-governance tool-group split (audit L-B2).

`desktop_observe` (read-only perception) and `desktop_control` (actuation) are
distinct tool-groups with NO overlap, so an agent can be granted perception
without ever being granted actuation. Pure logic over the static registry.
"""
from app.services.tool_groups import TOOL_GROUPS, resolve_tool_names

OBSERVE_TOOLS = {"desktop_observe_screen", "desktop_get_active_app", "desktop_read_clipboard"}
CONTROL_TOOLS = {
    "desktop_pointer_move",
    "desktop_pointer_click",
    "desktop_keyboard_type",
    "desktop_keyboard_key_chord",
}


def test_observe_and_control_groups_exist_and_are_distinct():
    assert "desktop_observe" in TOOL_GROUPS
    assert "desktop_control" in TOOL_GROUPS
    # the old monolithic group name is gone (it was observe-only, now renamed)
    assert set(TOOL_GROUPS["desktop_observe"]) == OBSERVE_TOOLS
    assert set(TOOL_GROUPS["desktop_control"]) == CONTROL_TOOLS


def test_observe_and_control_do_not_overlap():
    # the whole point of the split: no actuation tool leaks into the observe group
    assert OBSERVE_TOOLS.isdisjoint(CONTROL_TOOLS)
    assert set(TOOL_GROUPS["desktop_observe"]).isdisjoint(set(TOOL_GROUPS["desktop_control"]))


def test_observe_only_agent_cannot_actuate():
    # an agent granted ONLY desktop_observe resolves to perception tools, never
    # an actuation tool — the agent-governance boundary the split exists to enforce.
    resolved = set(resolve_tool_names(["desktop_observe"]))
    assert resolved == OBSERVE_TOOLS
    assert resolved.isdisjoint(CONTROL_TOOLS)


def test_control_group_resolves_to_actuation_tool_names():
    assert set(resolve_tool_names(["desktop_control"])) == CONTROL_TOOLS
