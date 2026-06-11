"""Desktop computer-use prompt context for Luna chat runtime.

The desktop MCP tools are already scoped by agent.tool_groups and the MCP
agent-token. These tests pin the runtime prompt layer so Luna knows how to use
the safe dry-run/status path from chat without exposing desktop guidance to
ordinary agents.
"""

from app.services.cli_session_manager import generate_cli_instructions


def _base_kwargs():
    return dict(
        skill_body="You are Luna.",
        tenant_name="752626d9-8b2c-4aa2-87ef-c458d48bd38a",
        user_name="simon",
        channel="web",
        conversation_summary="",
        memory_context={},
    )


def test_desktop_section_is_omitted_for_agents_without_desktop_groups():
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["knowledge_readonly", "meta"],
        desktop_context={"session_id": "session-123"},
    )

    assert "## Desktop Computer Use" not in out
    assert "desktop_background_app_control_dry_run" not in out


def test_desktop_control_section_renders_dry_run_status_guidance():
    session_id = "4c96cdbd-a326-48a2-b9ba-016e83a948f4"

    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_observe", "desktop_control"],
        desktop_context={
            "session_id": session_id,
            "default_target_bundle_id": "com.agentprovision.luna",
        },
    )

    assert "## Desktop Computer Use" in out
    assert f"Use session_id `{session_id}`" in out
    assert "desktop_background_app_control_dry_run" in out
    assert "desktop_command_status" in out
    assert "terminal status" in out
    assert "audit/event references" in out
    assert "`com.agentprovision.luna`" in out
    assert "Do not call pointer, click, keyboard" in out


def test_desktop_observe_only_section_does_not_suggest_control_tool():
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_observe"],
        desktop_context={"session_id": "session-123"},
    )

    assert "## Desktop Computer Use" in out
    assert "Observation tools return display-safe audit envelopes only" in out
    assert "desktop_background_app_control_dry_run" not in out
    assert "desktop_command_status" not in out


def test_desktop_section_fails_closed_without_session_id():
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_control"],
        desktop_context={},
    )

    assert "## Desktop Computer Use" in out
    assert "No desktop session_id is available" in out
    assert "do not call desktop MCP tools" in out
