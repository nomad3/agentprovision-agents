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
    # dry-run proof path is still offered
    assert "desktop_background_app_control_dry_run" in out
    assert "desktop_command_status" in out
    assert "terminal status" in out
    assert "audit/event references" in out
    assert "`com.agentprovision.luna`" in out


def test_desktop_control_section_describes_governed_approval_loop():
    # P5.4c: the chat-triggered loop over the already-merged tools. The agent
    # requests a grant, a human approves, the agent reads grant_id off status,
    # actuates, polls command status, and reports display-safe facts only.
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_control"],
        desktop_context={
            "session_id": "4c96cdbd-a326-48a2-b9ba-016e83a948f4",
            "default_target_bundle_id": "com.agentprovision.luna",
        },
    )

    assert "desktop_request_grant" in out
    assert "desktop_request_status" in out
    assert "grant_id" in out
    assert "desktop_actuate" in out
    # the agent cannot mint/approve its own grant — a human must approve
    assert "cannot approve your own request" in out
    assert "approval_required" in out
    # display-safe report-back contract
    assert "Report back only this allowlisted desktop-control summary" in out
    for allowed in (
        "action class",
        "capability",
        "outcome/status",
        "denial code",
        "command id",
        "desktop event id",
        "session event id",
        "audit/event references",
    ):
        assert allowed in out
    assert "Never quote OCR text" in out
    # Stop semantics
    assert "desktop_stop_commands" in out
    assert "revokes the" in out


def test_desktop_report_back_policy_names_every_raw_leak_source():
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_control"],
        desktop_context={
            "session_id": "4c96cdbd-a326-48a2-b9ba-016e83a948f4",
            "default_target_bundle_id": "com.agentprovision.luna",
        },
    )

    forbidden_guidance = [
        "OCR text",
        "window titles",
        "contact names",
        "clipboard values",
        "typed text",
        "raw screen content",
        "request reasons",
        "action args",
        "`text`",
        "`value`",
        "`title`",
        "`page_text`",
        "`ax_tree`",
    ]
    for term in forbidden_guidance:
        assert term in out
    assert "observed content was redacted" in out


def test_desktop_context_raw_fields_are_not_rendered_in_prompt():
    leak_values = {
        "ocr_text": "LEAK_OCR_BANK_BALANCE_123",
        "window_title": "LEAK_WINDOW_TITLE_PRIVATE_CHAT",
        "contact_name": "LEAK_CONTACT_PATIENT_NAME",
        "clipboard_text": "LEAK_CLIPBOARD_SECRET",
        "typed_text": "LEAK_TYPED_MESSAGE_BODY",
        "raw_screen_content": "LEAK_RAW_SCREEN_CONTENT",
        "action_args": {"text": "LEAK_ACTION_ARG_TEXT"},
        "ax_tree": "LEAK_AX_TREE_NODE",
    }
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_control"],
        desktop_context={
            "session_id": "4c96cdbd-a326-48a2-b9ba-016e83a948f4",
            "default_target_bundle_id": "com.agentprovision.luna",
            **leak_values,
        },
    )

    for value in leak_values.values():
        if isinstance(value, dict):
            value = value["text"]
        assert value not in out
    assert "com.agentprovision.luna" in out
    assert "4c96cdbd-a326-48a2-b9ba-016e83a948f4" in out


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
    # the act-loop tools must never leak to an observe-only agent
    assert "desktop_request_grant" not in out
    assert "desktop_actuate" not in out


def test_desktop_section_fails_closed_without_session_id():
    out = generate_cli_instructions(
        **_base_kwargs(),
        agent_tool_groups=["desktop_control"],
        desktop_context={},
    )

    assert "## Desktop Computer Use" in out
    assert "No desktop session_id is available" in out
    assert "do not call desktop MCP tools" in out
