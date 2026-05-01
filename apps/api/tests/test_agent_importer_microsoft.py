"""Importer tests for Microsoft Copilot Studio + Azure AI Foundry adoption.

Covers detection branches and the resulting Agent config (notably
`preferred_cli="copilot_cli"` and the explicit `autonomy_level="supervised"`
floor — both are what makes these imports wire into the GitHub Copilot CLI
runtime safely).
"""
from app.services.agent_importer import (
    detect_format,
    import_ai_foundry,
    import_copilot_studio,
    parse_agent_definition,
)


def test_detect_copilot_studio_via_schema_name():
    assert detect_format({"schemaName": "Microsoft.CopilotStudio.v1", "name": "X"}) == "copilot_studio"
    assert detect_format({"schemaName": "Microsoft.PowerVirtualAgents.bot"}) == "copilot_studio"


def test_detect_copilot_studio_via_kind_hint():
    assert detect_format({"kind": "copilot_studio", "name": "X"}) == "copilot_studio"
    assert detect_format({"kind": "PowerVirtualAgents", "name": "X"}) == "copilot_studio"


def test_detect_copilot_studio_via_botid_pair():
    assert detect_format({"botId": "abc", "directLineSecret": "s"}) == "copilot_studio"
    assert detect_format({"botId": "abc", "directline_token": "t"}) == "copilot_studio"


def test_detect_ai_foundry_via_kind_hint():
    assert detect_format({"kind": "ai_foundry"}) == "ai_foundry"
    assert detect_format({"kind": "azure_ai_agent"}) == "ai_foundry"


def test_detect_ai_foundry_assistants_shape_with_azure():
    payload = {
        "id": "asst_abc123",
        "model": "gpt-4o",
        "instructions": "Be helpful",
        "tools": [{"type": "code_interpreter"}],
    }
    assert detect_format(payload) == "ai_foundry"


def test_detect_ai_foundry_endpoint_indicator():
    payload = {
        "model": "gpt-4o",
        "instructions": "x",
        "tools": [],
        "endpoint": "https://my-resource.openai.azure.com",
    }
    assert detect_format(payload) == "ai_foundry"


def test_detect_does_not_misroute_assistants_shape_without_azure():
    """A bare model+instructions+tools dict (no Azure hint) must NOT match
    ai_foundry — that would steal CrewAI / generic Assistants payloads."""
    payload = {"model": "gpt-4", "instructions": "x", "tools": []}
    assert detect_format(payload) != "ai_foundry"


def test_import_copilot_studio_sets_runtime_override_and_floor():
    raw = {
        "schemaName": "Microsoft.CopilotStudio.v1",
        "displayName": "Acme Sales Bot",
        "description": "Helps with quotes",
        "generativeAI": {"instructions": "You are an Acme sales assistant."},
        "topics": [{"name": "pricing"}, {"displayName": "discounts"}],
        "botId": "bot-123",
    }
    out = import_copilot_studio(raw)
    assert out["name"] == "Acme Sales Bot"
    assert out["persona_prompt"] == "You are an Acme sales assistant."
    assert "pricing" in out["capabilities"]
    assert "discounts" in out["capabilities"]
    # Runtime override — this is the wiring that makes the Copilot CLI fire.
    assert out["config"]["preferred_cli"] == "copilot_cli"
    # Explicit supervised floor for externally-imported agents.
    assert out["autonomy_level"] == "supervised"
    # Audit trail preserves the raw payload.
    assert out["config"]["metadata"]["original"] == raw
    assert out["config"]["metadata"]["bot_id"] == "bot-123"


def test_import_copilot_studio_instruction_fallbacks():
    """Top-level instructions take precedence over generativeAI.instructions."""
    raw_top = {"schemaName": "Microsoft.CopilotStudio", "instructions": "TOP", "generativeAI": {"instructions": "NESTED"}}
    assert import_copilot_studio(raw_top)["persona_prompt"] == "TOP"

    raw_nested = {"schemaName": "Microsoft.CopilotStudio", "generativeAI": {"instructions": "NESTED"}}
    assert import_copilot_studio(raw_nested)["persona_prompt"] == "NESTED"

    raw_none = {"schemaName": "Microsoft.CopilotStudio", "generativeAI": "not-a-dict"}
    assert import_copilot_studio(raw_none)["persona_prompt"] == ""


def test_import_ai_foundry_sets_runtime_override_and_floor():
    raw = {
        "kind": "ai_foundry",
        "id": "asst_xyz789",
        "name": "Cardiology Assistant",
        "model": "gpt-4o",
        "instructions": "You read echocardiograms.",
        "tools": [{"type": "code_interpreter"}, "file_search"],
        "endpoint": "https://contoso.openai.azure.com",
    }
    out = import_ai_foundry(raw)
    assert out["name"] == "Cardiology Assistant"
    assert out["persona_prompt"] == "You read echocardiograms."
    assert "code_interpreter" in out["capabilities"]
    assert "file_search" in out["capabilities"]
    assert out["config"]["preferred_cli"] == "copilot_cli"
    assert out["autonomy_level"] == "supervised"
    # Source metadata preserved for audit / future Microsoft-live-API path.
    md = out["config"]["metadata"]
    assert md["agent_id"] == "asst_xyz789"
    assert md["model"] == "gpt-4o"
    assert md["endpoint"] == "https://contoso.openai.azure.com"


def test_parse_agent_definition_routes_microsoft_formats_first():
    """parse_agent_definition must hit the Microsoft branches before the
    generic fall-through, so a Copilot Studio export with `name` and
    `tools` doesn't get treated as a native generic agent."""
    import json
    payload = json.dumps({
        "schemaName": "Microsoft.CopilotStudio",
        "displayName": "Bot X",
        "instructions": "Be brief",
    })
    out = parse_agent_definition(payload)
    assert out["config"]["preferred_cli"] == "copilot_cli"
    assert out["config"]["metadata"]["source"] == "copilot_studio"
