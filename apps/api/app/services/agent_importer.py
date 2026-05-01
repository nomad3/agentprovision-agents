import json


def detect_format(content) -> str:
    if not isinstance(content, dict):
        return "unknown"
    # Microsoft Copilot Studio (low-code, Teams-native). Recognized via:
    #   - schemaName starting with Microsoft.{CopilotStudio,PowerVirtualAgents}
    #   - explicit kind hint
    #   - botId + directLineSecret pair (export from Copilot Studio bot config)
    schema_name = str(content.get("schemaName", ""))
    if schema_name.startswith(("Microsoft.PowerVirtualAgents", "Microsoft.CopilotStudio")):
        return "copilot_studio"
    if str(content.get("kind", "")).lower() in (
        "copilot_studio", "copilotstudio", "powervirtualagents"
    ):
        return "copilot_studio"
    if "botId" in content and ("directLineSecret" in content or "directline_token" in content):
        return "copilot_studio"
    # Azure AI Foundry Agent Service (Azure OpenAI Assistants-compatible).
    # Recognized via explicit kind, or the Assistants shape (model + instructions
    # + tools list) plus an Azure-flavored hint.
    if str(content.get("kind", "")).lower() in (
        "ai_foundry", "azure_ai_foundry", "azure_ai_agent"
    ):
        return "ai_foundry"
    if (
        "model" in content
        and "instructions" in content
        and isinstance(content.get("tools"), list)
        and (
            str(content.get("id", "")).startswith("asst_")
            or "azure" in str(content.get("provider", "")).lower()
            or str(content.get("endpoint", "")).endswith("openai.azure.com")
            or str(content.get("project_endpoint", "")).endswith("services.ai.azure.com")
        )
    ):
        return "ai_foundry"
    # Existing native formats.
    if "agents" in content and isinstance(content.get("agents"), list):
        agents = content["agents"]
        if agents and isinstance(agents[0], dict) and "role" in agents[0]:
            return "crewai"
    if "role" in content and "goal" in content:
        return "crewai"
    if "agent_type" in content:
        return "langchain"
    if "_type" in content and "agent" in str(content["_type"]).lower():
        return "langchain"
    if "name" in content and "system_message" in content:
        return "autogen"
    return "unknown"


def import_crewai(data: dict) -> dict:
    if "agents" in data and isinstance(data.get("agents"), list) and data["agents"]:
        source = data["agents"][0]
    else:
        source = data

    tools = source.get("tools", [])
    if tools and isinstance(tools[0], dict):
        tools = [t.get("name", str(t)) for t in tools]

    return {
        "name": source.get("role", "CrewAI Agent"),
        "description": source.get("goal", ""),
        "persona_prompt": source.get("backstory", ""),
        "capabilities": tools,
        "config": {"metadata": {"source": "crewai", "original": data}},
    }


def import_langchain(data: dict) -> dict:
    agent_type = data.get("agent_type") or data.get("_type", "")
    tools = data.get("tools", [])
    cap = [t.get("name", str(t)) if isinstance(t, dict) else str(t) for t in tools]

    return {
        "name": data.get("name", "LangChain Agent"),
        "description": data.get("description", f"Imported LangChain {agent_type} agent"),
        "persona_prompt": data.get("prefix", ""),
        "capabilities": cap,
        "config": {"metadata": {"source": "langchain", "agent_type": agent_type}},
    }


def import_autogen(data: dict) -> dict:
    name = data.get("name", "AutoGen Agent")
    system_message = data.get("system_message", "")
    code_execution_config = data.get("code_execution_config")
    function_map = data.get("function_map") or {}

    return {
        "name": name,
        "description": f"AutoGen agent: {name}",
        "persona_prompt": system_message,
        "capabilities": list(function_map.keys()),
        "config": {"metadata": {"source": "autogen", "code_execution": bool(code_execution_config)}},
    }


# ── Microsoft platforms — imported as NATIVE agents that run on
# GitHub Copilot CLI ────────────────────────────────────────────────
#
# Both Copilot Studio (low-code, Teams-native) and Azure AI Foundry
# Agent Service (Assistants-compatible REST) export agent definitions
# that AgentProvision adopts as **local** agents. The runtime is the
# already-integrated GitHub Copilot CLI (apps/code-worker `_execute_copilot_chat`),
# which authenticates with the tenant's GitHub OAuth token and bills
# against the tenant's GitHub Copilot subscription.
#
# We DON'T call out to Microsoft's billable APIs at runtime. We only
# adopt the agent's persona (instructions/system prompt) and capability
# surface (tools list).
#
# The `config.preferred_cli="copilot_cli"` override is honored by
# `agent_router.route_and_execute` ahead of the tenant's
# `default_cli_platform`, so these imported agents always run on the
# Copilot subscription regardless of tenant defaults.
#
# Dynamic workflow wiring is automatic: the existing `agent` step type
# resolves to `route_and_execute`, which now picks copilot_cli for these
# agents.


def import_copilot_studio(data: dict) -> dict:
    """Import a Microsoft Copilot Studio agent as a native Agent.

    Maps the imported config:
      - displayName/name → agent.name
      - description → agent.description
      - generative AI instructions / system prompt → agent.persona_prompt
      - topics → agent.capabilities (best-effort surface of skills)
      - everything else → agent.config.metadata.original (preserve for audit)

    Forces ``config.preferred_cli = "copilot_cli"`` so the Copilot
    subscription is the runtime regardless of tenant default CLI.
    """
    name = data.get("displayName") or data.get("name") or "Copilot Studio Agent"
    instructions = (
        data.get("instructions")
        or data.get("system_prompt")
        or data.get("persona_prompt")
        or data.get("generativeAI", {}).get("instructions")
        if isinstance(data.get("generativeAI"), dict)
        else (
            data.get("instructions")
            or data.get("system_prompt")
            or data.get("persona_prompt")
            or ""
        )
    )
    if not isinstance(instructions, str):
        instructions = str(instructions or "")

    topics = data.get("topics") or []
    if topics and isinstance(topics[0], dict):
        capabilities = [t.get("name") or t.get("displayName") or "topic" for t in topics]
    else:
        capabilities = [str(t) for t in topics] if topics else (data.get("capabilities") or [])

    return {
        "name": name,
        "description": data.get("description") or f"Microsoft Copilot Studio agent: {name}",
        "persona_prompt": instructions,
        "capabilities": capabilities,
        "config": {
            # Force runtime to the GitHub Copilot CLI — uses the tenant's
            # GitHub OAuth + Copilot subscription. Honored by agent_router.
            "preferred_cli": "copilot_cli",
            "metadata": {
                "source": "copilot_studio",
                "imported_from": "microsoft_copilot_studio",
                "bot_id": data.get("botId") or data.get("id"),
                "schema_name": data.get("schemaName"),
                "original": data,
            },
        },
    }


def import_ai_foundry(data: dict) -> dict:
    """Import an Azure AI Foundry Agent Service agent as a native Agent.

    Maps the imported config:
      - name → agent.name
      - instructions → agent.persona_prompt
      - tools (list of {type, ...} or names) → agent.capabilities
      - model / endpoint / agent_id → preserved in metadata

    Forces ``config.preferred_cli = "copilot_cli"``. The original Azure
    model preference (``gpt-4o``, etc.) is preserved in metadata for
    reference but isn't used at runtime — Copilot CLI picks its own
    model.
    """
    name = data.get("name") or "Azure AI Foundry Agent"
    instructions = data.get("instructions") or ""
    tools = data.get("tools") or []
    capabilities: list = []
    for t in tools:
        if isinstance(t, dict):
            capabilities.append(t.get("type") or t.get("name") or "tool")
        elif isinstance(t, str):
            capabilities.append(t)

    return {
        "name": name,
        "description": data.get("description") or f"Azure AI Foundry agent: {name}",
        "persona_prompt": instructions,
        "capabilities": capabilities,
        "config": {
            "preferred_cli": "copilot_cli",
            "metadata": {
                "source": "ai_foundry",
                "imported_from": "azure_ai_foundry",
                "agent_id": data.get("agent_id") or data.get("id"),
                "model": data.get("model"),
                "endpoint": data.get("project_endpoint") or data.get("endpoint"),
                "original": data,
            },
        },
    }


def parse_agent_definition(content: str, filename: str = "") -> dict:
    parsed = None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        pass

    if parsed is None:
        try:
            import yaml
            try:
                parsed = yaml.safe_load(content)
            except Exception:
                pass
        except ImportError:
            pass

    if not isinstance(parsed, dict):
        return {
            "name": filename or "Imported Agent",
            "description": "Imported agent (unknown format)",
            "capabilities": [],
            "config": {"metadata": {"source": "unknown", "raw": str(content)[:500]}},
        }

    fmt = detect_format(parsed)

    # Microsoft platforms — adopted as native agents that run on the
    # GitHub Copilot CLI (preferred_cli forced to copilot_cli).
    if fmt == "copilot_studio":
        return import_copilot_studio(parsed)
    if fmt == "ai_foundry":
        return import_ai_foundry(parsed)

    if fmt == "crewai":
        return import_crewai(parsed)
    if fmt == "langchain":
        return import_langchain(parsed)
    if fmt == "autogen":
        return import_autogen(parsed)

    # Native / generic format — accept any dict with at least a name or description
    name = parsed.get("name") or parsed.get("role") or filename or "Imported Agent"
    caps = parsed.get("capabilities") or parsed.get("skills") or parsed.get("tools") or []
    if caps and isinstance(caps[0], dict):
        caps = [c.get("name", str(c)) for c in caps]
    return {
        "name": name,
        "description": parsed.get("description") or parsed.get("goal") or "",
        "persona_prompt": parsed.get("persona_prompt") or parsed.get("system_prompt") or parsed.get("system_message") or "",
        "capabilities": caps,
        "config": parsed.get("config") or {"metadata": {"source": "native"}},
    }
