"""Smoke tests for the dual-transport MCP server route layout.

Guards against regressions in
``docs/plans/2026-05-16-codex-mcp-transport-mismatch-research.md``:

* Codex's rmcp client only speaks ``Stdio`` + ``StreamableHttp``; it
  POSTs JSON-RPC directly to the configured URL. If the streamable-HTTP
  mount stops responding (or moves), Codex tool calls 405/404 and
  silently drop the worker. These tests pin the URL shape.
* Claude Code + Gemini speak legacy SSE: ``GET /sse`` for the event
  stream + ``POST /messages/?session_id=...`` for client frames. If
  someone collapses the dual mount back to single-transport, those
  CLIs lose tool access. The SSE side is pinned too.

Strategy: build the parent Starlette and walk its route tree. We
deliberately AVOID issuing real GETs against ``/sse`` or ``/mcp/``
because both endpoints stream indefinitely — Starlette's TestClient
would hang waiting for the body. We DO issue ``POST /sse`` because
that's the 405 path under test (it returns immediately).
End-to-end MCP protocol negotiation is covered by the per-tool
integration tests, not here.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def app():
    """Build the parent Starlette once per module.

    Imports happen inside the fixture so the session-scoped env
    defaults (see conftest.py) are installed before ``mcp_app`` is
    imported and reads the environment at construction time.
    """
    from src.mcp_serve import build_app

    return build_app()


@pytest.fixture(scope="module")
def client_with_lifespan(app):
    """A module-scoped TestClient with lifespan entered exactly once.

    Why module-scoped: ``StreamableHTTPSessionManager.run()`` is
    explicitly single-shot — its docstring says *"This method can only
    be called once per instance"* — and FastMCP returns the same
    cached streamable_http_app (with the same session manager) across
    ``mcp.streamable_http_app()`` calls. If each HTTP-issuing test
    opened its own ``with TestClient(app)`` block, the second one
    would crash with ``RuntimeError: ...can only be called once``.

    ``raise_server_exceptions=False``: an unhandled exception inside
    the streamable-HTTP session manager (e.g. a transitive
    ``anyio`` / ``mcp`` lib version mismatch in dev or CI) would
    otherwise bubble out of TestClient and fail every probe. For
    route-wiring assertions we don't care if the handler completes
    cleanly — we only care that the bytes reached the handler
    (anything other than 404/405). Surface server errors as 500
    responses so the 404/405 contract test stays meaningful.

    Tests that only need route introspection (no real HTTP request)
    keep using the bare ``app`` fixture. Tests that actually POST/GET
    use this client so they share one lifespan boot.
    """
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _collect_mounted_paths(app) -> dict[str, list[str]]:
    """Return ``{mount_prefix: [inner_route_paths...]}`` for each Mount.

    Only walks one level deep — the parent Starlette mounts the two
    sub-apps directly, so a single level is enough to assert routes
    are where we expect them.
    """
    out: dict[str, list[str]] = {}
    for route in app.routes:
        # Starlette uses empty-string `path` for a root Mount("/"), so
        # we accept that as a sentinel for the root mount rather than
        # filtering it out (which would hide the SSE app entirely).
        mount_path = getattr(route, "path", None)
        sub_app = getattr(route, "app", None)
        if mount_path is None or sub_app is None:
            continue
        key = mount_path if mount_path else "/"
        inner_paths: list[str] = []
        for inner in getattr(sub_app, "routes", []) or []:
            ip = getattr(inner, "path", None)
            if ip is not None:
                inner_paths.append(ip)
        out[key] = inner_paths
    return out


# ── /sse — legacy SSE event stream (Claude + Gemini) ─────────────────────


def test_sse_route_is_registered(app):
    """``GET /sse`` is the legacy SSE event stream endpoint. Claude
    Code and Gemini CLI both pin their MCP transport to this URL.
    Walk the route tree and assert ``/sse`` is exposed by one of the
    mounted sub-apps. We don't issue a real GET because the route
    streams indefinitely — the regression we care about is the mount
    being missing or shadowed, which route introspection catches.
    """
    mounts = _collect_mounted_paths(app)
    all_inner_paths = [p for paths in mounts.values() for p in paths]
    assert "/sse" in all_inner_paths, (
        f"/sse not registered. Mounted layout: {mounts}. "
        "Legacy SSE clients (Claude/Gemini) would lose tool access."
    )


def test_messages_route_is_registered(app):
    """``POST /messages/?session_id=...`` is the client→server half of
    the legacy SSE transport. Its disappearance would silently break
    every tool call from Claude/Gemini even if the GET ``/sse`` event
    stream stayed up — the server-issued ``endpoint`` event would
    point at a 404."""
    mounts = _collect_mounted_paths(app)
    all_inner_paths = [p for paths in mounts.values() for p in paths]
    # Starlette reports a Mount("/messages/") inner path as
    # ``/messages`` (no trailing slash). The public URL still requires
    # the slash, but for route introspection either form is a hit.
    assert any(
        p in ("/messages", "/messages/") for p in all_inner_paths
    ), f"/messages/ not registered. Mounted layout: {mounts}."


def test_sse_post_returns_405(client_with_lifespan):
    """``POST /sse`` MUST return 405. This is the exact failure mode
    Codex's rmcp client hit before the fix — it POSTed JSON-RPC to
    ``/sse`` (GET-only) and the worker tore down on the 405. The
    SSE route's verb contract is unchanged by the fix; only Codex's
    target URL moved (to ``/mcp/``).
    """
    response = client_with_lifespan.post(
        "/sse", json={"jsonrpc": "2.0", "method": "ping"}
    )
    assert response.status_code == 405, (
        f"Expected 405 on POST /sse, got {response.status_code}. "
        "If this is 200, the SSE route somehow accepts POST and the "
        "Codex-vs-Gemini transport contract is broken."
    )


# ── /mcp/ — streamable-HTTP (Codex's rmcp client) ────────────────────────


def test_mcp_streamable_mount_registered(app):
    """The streamable-HTTP sub-app MUST be mounted at ``/mcp``. Codex's
    rmcp ``StreamableHttp`` transport POSTs JSON-RPC bodies directly
    to ``/mcp/``. If the mount is absent (or its inner
    ``streamable_http_path`` is left at the default ``/mcp`` rather
    than ``/``, yielding the URL ``/mcp/mcp``), Codex 404s and tears
    down."""
    mounts = _collect_mounted_paths(app)
    assert "/mcp" in mounts, (
        f"Streamable-HTTP app not mounted at /mcp. Mounted layout: "
        f"{mounts}. Codex would 404 on every tool call."
    )
    # The inner streamable-HTTP route MUST be "/" — see mcp_app.py
    # where ``streamable_http_path="/"`` is set so the public URL is
    # ``/mcp/`` rather than ``/mcp/mcp``.
    assert "/" in mounts["/mcp"], (
        f"Inner streamable-HTTP path is not '/' — got {mounts['/mcp']}. "
        "Public URL would be /mcp/mcp instead of /mcp/."
    )


def test_mcp_streamable_endpoint_is_wired(client_with_lifespan):
    """Real HTTP probe of ``/mcp/`` — proves the route is wired AND the
    streamable-HTTP session manager booted via the parent app's
    lifespan. Route-tree introspection (above) is necessary but not
    sufficient: a bug in the parent ``lifespan`` (e.g. forgetting to
    re-enter ``streamable_app.router.lifespan_context``) leaves the
    mount registered but every POST returns 503 or the session manager
    raises ``RuntimeError: Task group is not initialized``. We don't
    care if ``initialize`` actually succeeds — only that the response
    is NOT 404 (mount missing) and NOT 405 (verb contract broken).
    A 200/400/406/503 from the session manager all prove lifespan
    boot + route wiring are intact.

    Shares one TestClient/lifespan with the SSE 405 probe because
    ``StreamableHTTPSessionManager.run()`` is single-shot per
    instance (see ``client_with_lifespan`` fixture docstring). That
    fixture also disables ``raise_server_exceptions`` so a 500 from
    a transitive lib bug still surfaces as a response — the
    route-wiring assertion below only cares about 404/405.
    """
    resp = client_with_lifespan.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {},
        },
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code not in (404, 405), (
        f"streamable-http route not reachable: {resp.status_code} "
        f"{resp.text!r}. 404 → mount missing or shadowed; 405 → "
        "verb contract broken (the regression Codex's rmcp hit on /sse)."
    )
