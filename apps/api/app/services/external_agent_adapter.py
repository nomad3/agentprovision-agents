import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.models.external_agent import ExternalAgent
from app.models.integration_credential import IntegrationCredential
from app.services.orchestration.credential_vault import retrieve_credential

logger = logging.getLogger(__name__)

# Default budget for an MCP-SSE handshake + single tool call.
_MCP_SSE_DEFAULT_TIMEOUT = 30


class ExternalAgentAdapter:
    def dispatch(self, agent: ExternalAgent, task: str, context: dict, db: Session) -> str:
        """Route task to external agent based on protocol."""
        if agent.protocol == "openai_chat":
            return self._dispatch_openai_chat(agent, task, context, db)
        elif agent.protocol == "mcp_sse":
            return self._dispatch_mcp_sse(agent, task, context, db)
        elif agent.protocol == "webhook":
            return self._dispatch_webhook(agent, task, context, db)
        elif agent.protocol == "copilot_studio":
            return self._dispatch_copilot_studio(agent, task, context, db)
        elif agent.protocol == "ai_foundry":
            return self._dispatch_ai_foundry(agent, task, context, db)
        elif agent.protocol == "a2a":
            return "A2A dispatch not yet implemented for external agent adapter"
        elif agent.protocol == "copilot_extension":
            return "Copilot Extension dispatch not yet implemented"
        else:
            raise RuntimeError(f"Unknown protocol: {agent.protocol}")

    # ── Microsoft Copilot Studio (Direct Line API) ───────────────────

    def _dispatch_copilot_studio(
        self, agent: ExternalAgent, task: str, context: dict, db: Session
    ) -> str:
        """Dispatch to a Microsoft Copilot Studio bot via Direct Line.

        Each call: start a fresh conversation, send the user message, poll
        activities until we have a bot reply, return the bot's text.

        Stateless from our side — Copilot Studio has its own conversation
        memory keyed off the `from.id` we pass. To preserve continuity
        across calls within the same chat session, the caller can pass
        `context["copilot_user_id"]` to keep the same conversational state.
        """
        import time

        meta = agent.metadata_ or {}
        bot_id = meta.get("bot_id") or ""
        # Direct Line auth: prefer credential_id if set, fall back to the
        # bootstrap secret stored in metadata.
        secret = self._get_credential(agent, db) or meta.get("directline_secret")
        if not secret:
            raise RuntimeError(
                f"Copilot Studio agent '{agent.name}' has no Direct Line secret"
            )
        base = (agent.endpoint_url or "https://directline.botframework.com/v3/directline").rstrip("/")
        headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
        user_id = (context or {}).get("copilot_user_id") or "agentprovision"

        with httpx.Client(timeout=agent.metadata_.get("timeout", 30)) as client:
            try:
                conv = client.post(f"{base}/conversations", headers=headers)
                conv.raise_for_status()
                conv_id = conv.json()["conversationId"]

                client.post(
                    f"{base}/conversations/{conv_id}/activities",
                    headers=headers,
                    json={"type": "message", "from": {"id": user_id}, "text": task},
                ).raise_for_status()

                # Poll up to ~10 attempts for the bot reply.
                watermark = None
                for _ in range(10):
                    time.sleep(1.0)
                    url = f"{base}/conversations/{conv_id}/activities"
                    if watermark:
                        url += f"?watermark={watermark}"
                    acts = client.get(url, headers=headers)
                    acts.raise_for_status()
                    payload = acts.json()
                    watermark = payload.get("watermark") or watermark
                    bot_replies = [
                        a for a in (payload.get("activities") or [])
                        if a.get("type") == "message"
                        and (a.get("from") or {}).get("id") != user_id
                        and (a.get("text") or "").strip()
                    ]
                    if bot_replies:
                        return "\n".join(a["text"] for a in bot_replies)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"copilot_studio dispatch failed with status {e.response.status_code}"
                ) from e
        return "(no reply from copilot studio agent within timeout)"

    # ── Azure AI Foundry Agent Service (Assistants-compatible REST) ──

    def _dispatch_ai_foundry(
        self, agent: ExternalAgent, task: str, context: dict, db: Session
    ) -> str:
        """Dispatch to an Azure AI Foundry Agent Service agent.

        Foundry's Agent Service exposes an Assistants-compatible API:

          POST   {endpoint}/threads
          POST   {endpoint}/threads/{thread_id}/messages
          POST   {endpoint}/threads/{thread_id}/runs
          GET    {endpoint}/threads/{thread_id}/runs/{run_id}
          GET    {endpoint}/threads/{thread_id}/messages

        We persist the thread_id on the agent's metadata after first call so
        subsequent dispatches preserve conversation continuity.
        """
        import time

        meta = dict(agent.metadata_ or {})
        agent_id = meta.get("agent_id") or ""
        endpoint = (agent.endpoint_url or "").rstrip("/")
        if not (endpoint and agent_id):
            raise RuntimeError(
                f"AI Foundry agent '{agent.name}' missing endpoint or agent_id"
            )
        token = self._get_credential(agent, db)
        if not token:
            raise RuntimeError(
                f"AI Foundry agent '{agent.name}' has no auth credential"
            )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2",
        }
        # Foundry's REST is versioned; the api-version query param is required.
        api_version = meta.get("api_version", "2024-12-01-preview")
        params = {"api-version": api_version}

        with httpx.Client(timeout=agent.metadata_.get("timeout", 60)) as client:
            try:
                # 1. Reuse or create a thread.
                thread_id = meta.get("thread_id")
                if not thread_id:
                    thr = client.post(
                        f"{endpoint}/threads", headers=headers, params=params, json={}
                    )
                    thr.raise_for_status()
                    thread_id = thr.json()["id"]
                    meta["thread_id"] = thread_id
                    agent.metadata_ = meta
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(agent, "metadata_")
                    db.commit()

                # 2. Add user message.
                client.post(
                    f"{endpoint}/threads/{thread_id}/messages",
                    headers=headers,
                    params=params,
                    json={"role": "user", "content": task},
                ).raise_for_status()

                # 3. Start a run.
                run = client.post(
                    f"{endpoint}/threads/{thread_id}/runs",
                    headers=headers,
                    params=params,
                    json={"assistant_id": agent_id},
                )
                run.raise_for_status()
                run_id = run.json()["id"]

                # 4. Poll until the run is terminal.
                terminal = {"completed", "failed", "cancelled", "expired", "requires_action"}
                for _ in range(60):
                    time.sleep(1.0)
                    r = client.get(
                        f"{endpoint}/threads/{thread_id}/runs/{run_id}",
                        headers=headers, params=params,
                    )
                    r.raise_for_status()
                    state = r.json().get("status")
                    if state in terminal:
                        if state != "completed":
                            return f"(ai_foundry run ended in state: {state})"
                        break
                else:
                    return "(ai_foundry run timed out)"

                # 5. Read the latest assistant message.
                msgs = client.get(
                    f"{endpoint}/threads/{thread_id}/messages",
                    headers=headers, params={**params, "order": "desc", "limit": 1},
                )
                msgs.raise_for_status()
                items = (msgs.json() or {}).get("data") or []
                if not items:
                    return "(ai_foundry returned no messages)"
                first = items[0]
                if first.get("role") != "assistant":
                    return "(ai_foundry latest message is not from the assistant)"
                content_parts = first.get("content") or []
                texts = []
                for part in content_parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(((part.get("text") or {}).get("value") or ""))
                return "\n".join(t for t in texts if t).strip() or "(empty assistant reply)"
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"ai_foundry dispatch failed with status {e.response.status_code}: {e.response.text[:200]}"
                ) from e

    def _dispatch_openai_chat(self, agent: ExternalAgent, task: str, context: dict, db: Session) -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": str(context)})
        messages.append({"role": "user", "content": task})

        token = self._get_credential(agent, db)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "model": agent.metadata_.get("model", "gpt-4"),
            "messages": messages,
        }

        try:
            resp = httpx.post(
                f"{agent.endpoint_url.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
                timeout=agent.metadata_.get("timeout", 30),
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"openai_chat request failed with status {e.response.status_code}") from e
        except Exception as e:
            raise RuntimeError(f"openai_chat request failed: {e}") from e

    def _dispatch_webhook(self, agent: ExternalAgent, task: str, context: dict, db: Session) -> str:
        payload = {"task": task, "context": context, "callback_url": None}
        body_json = json.dumps(payload)

        headers = {"Content-Type": "application/json"}
        if agent.auth_type == "hmac":
            secret = self._get_credential(agent, db)
            sig = hmac.new(secret.encode(), body_json.encode(), hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"hmac-sha256={sig}"
        else:
            token = self._get_credential(agent, db)
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = httpx.post(
                f"{agent.endpoint_url.rstrip('/')}/tasks",
                content=body_json,
                headers=headers,
                timeout=agent.metadata_.get("timeout", 30),
            )
            if resp.status_code == 200:
                return str(resp.json())
            raise RuntimeError(f"webhook request failed with status {resp.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"webhook request failed: {e}") from e

    def _dispatch_mcp_sse(self, agent: ExternalAgent, task: str, context: dict, db: Session) -> str:
        """Dispatch a task to a remote MCP server over SSE.

        Most Claude Code / Gemini / Cursor "skills" are exposed as MCP-SSE
        servers. We open one short-lived connection per dispatch:
            connect → initialize → list_tools (cached) → call_tool → close.

        Tool selection precedence:
          1. ``context["tool_name"]`` (caller-supplied — e.g. from Dynamic
             Workflow step config).
          2. ``agent.metadata_["tool_name"]`` (set during Hire so the
             external agent has a default action).
          3. First tool returned by ``list_tools`` — only used when the
             remote server exposes a single primary tool. Multi-tool servers
             with no explicit selection raise.

        Tool arguments precedence:
          1. ``context["arguments"]`` if it's a dict — full structured args.
          2. ``{"input": task}`` fallback — most single-tool agents accept
             a free-text input field.

        The adapter is sync (chat path) but the official MCP SDK is async,
        so we drive it via ``asyncio.run`` per dispatch. Acceptable here:
        external dispatch is low-frequency and we want a fresh connection
        per call to keep the breaker semantics in PR-C clean.
        """
        token = self._get_credential(agent, db)
        timeout_s = int(agent.metadata_.get("timeout", _MCP_SSE_DEFAULT_TIMEOUT) or _MCP_SSE_DEFAULT_TIMEOUT)
        tool_name = (
            (context.get("tool_name") if isinstance(context, dict) else None)
            or agent.metadata_.get("tool_name")
        )
        arguments = (context.get("arguments") if isinstance(context, dict) else None)
        if not isinstance(arguments, dict):
            arguments = {"input": task}

        # Only Bearer-style auth is supported for MCP-SSE today; other
        # auth_types (api_key / hmac / github_app) would need request-level
        # signing the SDK doesn't expose. Skip the Authorization header
        # rather than send the wrong one — the remote will surface the
        # auth failure clearly.
        bearer = token if (token and getattr(agent, "auth_type", "bearer") == "bearer") else ""

        try:
            return _run_async(
                self._mcp_sse_call(
                    endpoint=agent.endpoint_url,
                    bearer=bearer,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout_s=timeout_s,
                )
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"mcp_sse request failed: {e}") from e

    @staticmethod
    async def _mcp_sse_call(
        *,
        endpoint: str,
        bearer: str,
        tool_name: Optional[str],
        arguments: dict,
        timeout_s: int,
    ) -> str:
        # Imported lazily so api startup doesn't pay the cost when no
        # external MCP agent is registered.
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        headers: dict[str, str] = {}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        # The mcp SDK's sse_client takes the *messages* endpoint URL —
        # remote servers usually expose it at <base>/sse. Honor whatever
        # the user registered; only append /sse if the URL has no path.
        url = endpoint.rstrip("/")
        if not url.endswith("/sse"):
            # Heuristic: if the URL has no path beyond the host, the SSE
            # endpoint is conventionally at /sse. Otherwise trust the user.
            from urllib.parse import urlparse
            if not (urlparse(url).path or "").strip("/"):
                url = url + "/sse"

        async def _do() -> str:
            async with sse_client(url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    resolved_tool = tool_name
                    if not resolved_tool:
                        listing = await session.list_tools()
                        names = [t.name for t in (listing.tools or [])]
                        if not names:
                            raise RuntimeError("Remote MCP server exposes no tools.")
                        if len(names) > 1:
                            raise RuntimeError(
                                "Remote MCP server exposes multiple tools "
                                f"({names!r}); set agent.metadata_['tool_name'] "
                                "or pass context['tool_name']."
                            )
                        resolved_tool = names[0]

                    result = await session.call_tool(resolved_tool, arguments=arguments)
                    return _stringify_mcp_result(result)

        return await asyncio.wait_for(_do(), timeout=timeout_s)

    def _get_credential(self, agent: ExternalAgent, db: Session) -> str:
        if agent.credential_id is None:
            return ""
        try:
            plaintext = retrieve_credential(db, agent.credential_id, agent.tenant_id)
            return plaintext or ""
        except Exception as e:
            logger.warning("Could not load credential %s for agent %s: %s", agent.credential_id, agent.id, e)
            return ""


def _run_async(coro):
    """Drive an async coroutine from a sync caller, even when an event
    loop is already running (e.g. an async FastAPI handler calling the
    sync adapter). ``asyncio.run`` raises ``RuntimeError`` in that case;
    we detect the active loop and run the coroutine in a thread instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — the common case from sync chat / Temporal
        # activities. Use the simple path.
        return asyncio.run(coro)

    # We're inside a running event loop. Push the coroutine onto a fresh
    # loop in a worker thread so we don't deadlock.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _stringify_mcp_result(result: Any) -> str:
    """Flatten an MCP CallToolResult into a single string for the chat path.

    The SDK returns ``content`` as a list of typed blocks (TextContent,
    ImageContent, EmbeddedResource…). Adapter callers expect a string,
    matching the openai_chat / webhook contract. We concatenate text
    blocks; non-text blocks fall back to repr so nothing silently drops.
    """
    if result is None:
        return ""
    if getattr(result, "isError", False):
        # Surface the remote error in the same shape the adapter raises for
        # other protocols so the caller's try/except path is uniform.
        msg = getattr(result, "content", None) or "remote MCP tool returned an error"
        raise RuntimeError(f"mcp_sse tool returned error: {_join_content(msg)}")
    return _join_content(getattr(result, "content", None))


def _join_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        # TextContent has .text; other block types don't — fall back to repr.
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else repr(block))
    return "\n".join(parts)


adapter = ExternalAgentAdapter()
