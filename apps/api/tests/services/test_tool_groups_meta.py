"""Sanity tests for the `meta` tool group.

Luna needs platform-introspection tools to answer "list my agents",
"what workflows do I have", etc. The `meta` group bundles those tools
together so it can be attached to Luna (and any future supervisor) via
a single tool_groups entry. These tests pin:

* the group exists,
* it isn't empty,
* tool names are strings,
* at least one of the well-known introspection tools is present.

If any of these break, Luna's "list my agents" path regresses to the
"I couldn't access the live MCP registry" failure mode that motivated
the group in the first place.
"""

from app.services.tool_groups import TOOL_GROUPS, resolve_tool_names


def test_meta_group_registered() -> None:
    assert "meta" in TOOL_GROUPS, "`meta` tool group missing from TOOL_GROUPS"


def test_meta_group_non_empty_string_names() -> None:
    tools = TOOL_GROUPS["meta"]
    assert tools, "`meta` tool group is empty"
    for name in tools:
        assert isinstance(name, str) and name, f"invalid tool name in meta group: {name!r}"


def test_meta_group_contains_core_introspection_tool() -> None:
    expected_any = {"find_agent", "list_dynamic_workflows", "list_skills"}
    present = set(TOOL_GROUPS["meta"]) & expected_any
    assert present, (
        "meta group must contain at least one of "
        f"{sorted(expected_any)}; got {TOOL_GROUPS['meta']!r}"
    )


def test_resolve_tool_names_includes_meta_tools() -> None:
    # End-to-end: when a Luna-style agent declares tool_groups=["meta"],
    # the resolver must surface those names so the CLI orchestrator
    # passes them through --allowedTools.
    resolved = resolve_tool_names(["meta"])
    assert resolved is not None
    assert "find_agent" in resolved or "list_dynamic_workflows" in resolved
