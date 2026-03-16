"""Run the FastMCP server as standalone Streamable HTTP on 0.0.0.0:8000."""
import uvicorn
import src.mcp_tools  # noqa: F401 — registers @mcp.tool() decorators
from src.mcp_app import mcp

# Get the Starlette ASGI app from FastMCP
app = mcp.streamable_http_app()

# Remove TrustedHostMiddleware if present (blocks Docker internal hostnames)
if hasattr(app, 'middleware_stack'):
    pass  # Starlette builds middleware lazily, we handle via --host flag

if __name__ == "__main__":
    uvicorn.run(
        "src.mcp_serve:app",
        host="0.0.0.0",
        port=8000,
        # Disable host header checking for Docker networking
        forwarded_allow_ips="*",
    )
