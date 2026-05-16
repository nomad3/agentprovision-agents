"""Run the FastMCP server with BOTH legacy SSE and streamable-HTTP transports.

Why both:
  * Claude Code and Gemini CLI speak legacy SSE: ``GET /sse`` for the event
    stream + ``POST /messages/?session_id=...`` for client→server frames.
    Gemini's HTTP MCP client sends ``Accept: application/json`` only, which
    FastMCP's streamable-HTTP transport rejects with 406 — so SSE is the
    only path that works for it.
  * Codex CLI's rmcp client (activated by
    ``experimental_use_rmcp_client = true``) only implements ``Stdio`` and
    ``StreamableHttp`` — no legacy SSE variant. It POSTs JSON-RPC bodies
    directly to the configured URL. Pointing it at our ``/sse`` endpoint
    returns ``405 Method Not Allowed`` because that route is GET-only.

Fix (2026-05-16): mount both transport sub-apps under a parent Starlette
so each client speaks the protocol it actually supports. Legacy clients
keep using ``/sse`` (+ ``/messages/``); Codex's rmcp client uses
``/mcp/``. Same container, same port (8086), no new service.

Auth note: FastMCP doesn't run any HTTP middleware in this server today —
tenant + internal-key checks happen inside each tool via
``mcp_auth.resolve_auth_context(ctx)``, which reads request headers off
the per-tool RequestContext. Both transports plumb HTTP headers into
that context the same way, so the auth gate works uniformly without any
middleware lifting.

See ``docs/plans/2026-05-16-codex-mcp-transport-mismatch-research.md``.
"""
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

import src.mcp_tools  # noqa: F401 — registers @mcp.tool() decorators
from src.mcp_app import mcp
from src.tool_audit import install_audit

# Wrap mcp.call_tool with audit logging. Idempotent; audit failures
# never propagate to callers (see tool_audit._log_call).
install_audit(mcp)


def build_app() -> Starlette:
    """Compose a parent Starlette that serves both MCP transports.

    Layout:
      * ``/``     — legacy SSE app: exposes ``GET /sse`` (event stream)
                    and ``POST /messages/?session_id=...`` (client frames).
      * ``/mcp``  — streamable-HTTP app: single endpoint accepting POST
                    + GET, used by rmcp-style clients (Codex 0.20+).

    The streamable-HTTP sub-app carries its own ``lifespan`` that boots
    the ``StreamableHTTPSessionManager``. We delegate to it explicitly
    via the parent's ``lifespan`` hook because Starlette does NOT run
    sub-app lifespans on mounted ASGI apps by default.
    """
    sse_app = mcp.sse_app()
    streamable_app = mcp.streamable_http_app()

    # ── Lifespan delegation ─────────────────────────────────────────
    # The streamable-HTTP app's session manager needs its run() coroutine
    # alive for the duration of the server. The SSE app has no lifespan.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        # ``streamable_app.router.lifespan_context`` is the
        # ``lambda app: self.session_manager.run()`` set inside
        # FastMCP.streamable_http_app(). Re-entering it here boots the
        # session manager exactly once for the parent app's lifetime.
        async with streamable_app.router.lifespan_context(streamable_app):
            yield

    # NOTE on route ordering: Starlette matches mounts in order. The
    # streamable-HTTP mount MUST come before the catch-all ``/`` mount —
    # otherwise the SSE app (which doesn't define a route for ``/mcp/``)
    # would match first and return 404. mcp_app.py overrides the
    # streamable app's inner ``streamable_http_path`` to ``/`` so the
    # public URL collapses to ``/mcp/`` rather than ``/mcp/mcp``.
    return Starlette(
        routes=[
            Mount("/mcp", app=streamable_app),
            Mount("/", app=sse_app),
        ],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    app = build_app()
    uvicorn.run(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
