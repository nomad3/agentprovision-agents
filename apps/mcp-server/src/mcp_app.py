"""Unified MCP server for AgentProvision tools."""
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "agentprovision.com",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=8086,
    # The streamable-HTTP sub-app is mounted at ``/mcp`` by the parent
    # Starlette (see ``mcp_serve.py::build_app``). Override the inner
    # route to ``/`` so the public URL is ``/mcp/`` instead of the default
    # ``/mcp/mcp``. The legacy SSE paths (``/sse`` + ``/messages/``)
    # remain at their defaults — they get mounted at the parent's root.
    streamable_http_path="/",
    # Disable DNS rebinding protection for Docker internal networking
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)
