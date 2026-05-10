"""Claude Code chat executor — hoisted from workflows.py in Phase 1.6.

Body is byte-identical to the previous ``_execute_claude_chat`` (just
renamed to ``execute_claude_chat`` and with the two helper calls
rewired to the new ``cli_runtime`` module). Workflows-side helpers
(``_fetch_claude_token``, ``_INTEGRATION_NOT_CONNECTED_MESSAGES``,
``_build_allowed_tools_from_mcp``, the ``ChatCliResult``
dataclasses, and the module-level constants) are imported lazily inside
the function body so:

  1. The import cycle ``workflows -> cli_executors -> workflows`` does
     not fire at module-load time (workflows imports executors via the
     dispatch table inside ``execute_chat_cli``).
  2. Existing test monkeypatches on ``wf._fetch_claude_token`` etc. still
     take effect — lazy imports re-resolve the attribute on every call.
"""
from __future__ import annotations

import json
import os

import cli_runtime


def execute_claude_chat(task_input, session_dir: str):
    from workflows import (
        _fetch_claude_token,
        _INTEGRATION_NOT_CONNECTED_MESSAGES,
        _build_allowed_tools_from_mcp,
        ChatCliResult,
        WORKSPACE,
        CLAUDE_CODE_MODEL,
    )
    token = _fetch_claude_token(task_input.tenant_id)
    if not token:
        # Canonical not-connected message — must match
        # `cli_platform_resolver._MISSING_CRED_PATTERNS` so the
        # resolver chain classifies this as `missing_credential`
        # (skip without cooldown). The short form "Claude Code not
        # connected" did NOT match the regex (only the long
        # "subscription is not connected" did) — that broke chain
        # fallback for tenants who hit a credential-missing CLI.
        return ChatCliResult(
            response_text="",
            success=False,
            error=_INTEGRATION_NOT_CONNECTED_MESSAGES["claude_code"],
        )

    if task_input.instruction_md_content:
        with open(os.path.join(session_dir, "CLAUDE.md"), "w") as f:
            f.write(task_input.instruction_md_content)

    if task_input.mcp_config:
        with open(os.path.join(session_dir, "mcp.json"), "w") as f:
            f.write(task_input.mcp_config)

    _model = task_input.model or CLAUDE_CODE_MODEL
    _allowed = task_input.allowed_tools or _build_allowed_tools_from_mcp(
        task_input.mcp_config, extra="Bash,Read,Edit,Write,WebFetch,WebSearch"
    )
    
    prompt = task_input.message
    if task_input.instruction_md_content.strip():
        # Bypass the 20KB limit of --append-system-prompt by injecting
        # instructions and conversation history directly into the prompt.
        prompt = f"{task_input.instruction_md_content.strip()}\n\n# User Request\n\n{task_input.message}"

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", _model,
        "--allowedTools", _allowed,
        "--add-dir", session_dir,
    ]
    if os.path.isdir(WORKSPACE):
        cmd.extend(["--add-dir", WORKSPACE])

    # NOTE: --resume intentionally NOT used. Previously we stored an
    # ever-growing session_id per chat and resumed it on every message.
    # For long conversations (Luna on WhatsApp), the JSONL session file
    # grew to 16+ MB, causing:
    #   - slow startup (loading + parsing the full file)
    #   - lossy context compaction (old details silently dropped)
    #   - context loss on specific entities (names, prior lead gen lists)
    # Instead, each `claude -p` invocation is a fresh one-shot session,
    # and the caller (chat.py) is responsible for passing the last N
    # messages via --append-system-prompt. This gives deterministic,
    # bounded context under our control.
    # Use --no-session-persistence to avoid leaking JSONL files on every
    # call (842+ files were accumulated in the previous model).
    cmd.append("--no-session-persistence")

    mcp_path = os.path.join(session_dir, "mcp.json")
    if os.path.exists(mcp_path):
        cmd.extend(["--mcp-config", mcp_path])

    env = os.environ.copy()
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token

    result = cli_runtime.run_cli_with_heartbeat(
        cmd,
        label="Claude Code",
        timeout=1500,
        env=env,
        cwd=WORKSPACE if os.path.isdir(WORKSPACE) else session_dir,
    )
    if result.returncode != 0:
        err = cli_runtime.safe_cli_error_snippet(result.stderr, result.stdout, 1000)
        return ChatCliResult(response_text="", success=False, error=f"CLI exit {result.returncode}: {err}")

    raw = result.stdout.strip()
    if not raw:
        return ChatCliResult(response_text="", success=False, error="CLI produced no output")

    try:
        data = json.loads(raw)
        text = data.get("result") or data.get("response") or data.get("content") or data.get("text") or raw
        meta = {
            "platform": "claude_code",
            "input_tokens": (data.get("usage") or {}).get("input_tokens", 0),
            "output_tokens": (data.get("usage") or {}).get("output_tokens", 0),
            "model": data.get("model"),
            "claude_session_id": data.get("session_id", ""),
            "cost_usd": data.get("total_cost_usd", 0),
        }
        return ChatCliResult(response_text=text, success=True, metadata=meta)
    except json.JSONDecodeError:
        return ChatCliResult(
            response_text=raw,
            success=True,
            metadata={"platform": "claude_code"},
        )
