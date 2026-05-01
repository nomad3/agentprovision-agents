import json


def detect_format(content) -> str:
    if not isinstance(content, dict):
        return "unknown"
    # Microsoft Copilot Studio export — has botId + directline token endpoint, OR
    # a "schemaName" starting with "Microsoft.PowerVirtualAgents" / "Microsoft.CopilotStudio".
    schema_name = str(content.get("schemaName", ""))
    if schema_name.startswith(("Microsoft.PowerVirtualAgents", "Microsoft.CopilotStudio")):
        return "copilot_studio"
    if "botId" in content and ("directLineSecret" in content or "directline_token" in content):
        return "copilot_studio"
    if "kind" in content and str(content.get("kind", "")).lower() in (
        "copilot_studio", "copilotstudio", "powervirtualagents"
    ):
        return "copilot_studio"
    # Azure AI Foundry Agent Service export — has "model" + "instructions" + "tools" array
    # and either an "id" starting with "asst_" (compatible with Azure OpenAI Assistants
    # format) or an explicit "kind" / "platform" hint.
    if "kind" in content and str(content.get("kind", "")).lower() in (
        "ai_foundry", "azure_ai_foundry", "azure_ai_agent"
    ):
        return "ai_foundry"
    if (
        "model" in content
        and "instructions" in content
        and isinstance(content.get("tools"), list)
        and (str(content.get("id", "")).startswith("asst_") or "azure" in str(content.get("provider", "")).lower())
    ):
        return "ai_foundry"
    # Existing formats
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


def import_copilot_studio(data: dict) -> dict:
    """Import a Microsoft Copilot Studio agent.

    Copilot Studio agents are remote — they live in Microsoft's cloud and
    speak the Bot Framework Direct Line protocol. We register them as
    ExternalAgent rows (protocol='copilot_studio') and dispatch via the
    existing CopilotStudioClient (apps/mcp-server/src/mcp_tools/copilot_studio.py).

    Expected input shape (any of these work):
      - {"botId": "...", "directLineSecret": "...", "name": "..."}
      - {"botId": "...", "directline_token": "...", "name": "..."}
      - {"schemaName": "Microsoft.CopilotStudio.Agent", "name": "...", "id": "..."}
    """
    name = data.get("name") or data.get("displayName") or "Copilot Studio Agent"
    bot_id = data.get("botId") or data.get("id") or ""
    secret = data.get("directLineSecret") or data.get("directline_token") or ""
    capabilities = data.get("capabilities") or data.get("topics") or []
    return {
        "kind": "external",
        "name": name,
        "description": data.get("description") or f"Microsoft Copilot Studio agent: {name}",
        "protocol": "copilot_studio",
        "endpoint_url": "https://directline.botframework.com/v3/directline",
        "auth_type": "bearer",
        "capabilities": capabilities,
        "metadata": {
            "source": "copilot_studio",
            "bot_id": bot_id,
            # Secret is held here only for the bootstrap; production should
            # move it to the credential vault and reference via credential_id.
            "directline_secret": secret,
        },
    }


def import_ai_foundry(data: dict) -> dict:
    """Import an Azure AI Foundry Agent Service agent.

    AI Foundry agents are remote — Azure-hosted. The Agent Service exposes
    an OpenAI Assistants-compatible REST API at
    ``{project_endpoint}/agents/{agent_id}``. We register them as
    ExternalAgent rows (protocol='ai_foundry') and dispatch via the
    Foundry-aware adapter (Threads → Runs polling, similar to Assistants).

    Expected input shape (any of these work):
      - {"id": "asst_...", "model": "...", "instructions": "...", "tools": [...],
         "endpoint": "https://<project>.openai.azure.com"}
      - {"kind": "ai_foundry", "name": "...", "agent_id": "...",
         "project_endpoint": "https://<project>.services.ai.azure.com"}
    """
    name = data.get("name") or "Azure AI Foundry Agent"
    agent_id = data.get("agent_id") or data.get("id") or ""
    endpoint = (
        data.get("project_endpoint")
        or data.get("endpoint")
        or data.get("base_url")
        or ""
    )
    instructions = data.get("instructions") or ""
    tools = data.get("tools") or []
    capabilities: list[str] = []
    for t in tools:
        if isinstance(t, dict):
            capabilities.append(t.get("type") or t.get("name") or "tool")
        elif isinstance(t, str):
            capabilities.append(t)
    return {
        "kind": "external",
        "name": name,
        "description": data.get("description") or f"Azure AI Foundry agent: {name}",
        "persona_prompt": instructions,
        "protocol": "ai_foundry",
        "endpoint_url": endpoint,
        "auth_type": "bearer",
        "capabilities": capabilities,
        "metadata": {
            "source": "ai_foundry",
            "agent_id": agent_id,
            "model": data.get("model"),
            "thread_id": None,  # populated lazily on first dispatch
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

    # Remote / external agents — return a different shape (kind="external")
    # so the caller creates an ExternalAgent row instead of a native Agent.
    if fmt == "copilot_studio":
        return import_copilot_studio(parsed)
    if fmt == "ai_foundry":
        return import_ai_foundry(parsed)

    # Native agents — local config only.
    if fmt == "crewai":
        result = import_crewai(parsed)
    elif fmt == "langchain":
        result = import_langchain(parsed)
    elif fmt == "autogen":
        result = import_autogen(parsed)
    else:
        # Native / generic format — accept any dict with at least a name or description
        name = parsed.get("name") or parsed.get("role") or filename or "Imported Agent"
        caps = parsed.get("capabilities") or parsed.get("skills") or parsed.get("tools") or []
        if caps and isinstance(caps[0], dict):
            caps = [c.get("name", str(c)) for c in caps]
        result = {
            "name": name,
            "description": parsed.get("description") or parsed.get("goal") or "",
            "persona_prompt": parsed.get("persona_prompt") or parsed.get("system_prompt") or parsed.get("system_message") or "",
            "capabilities": caps,
            "config": parsed.get("config") or {"metadata": {"source": "native"}},
        }
    result.setdefault("kind", "native")
    return result
