"""Phase 1.6 public-surface smoke tests.

After commits 1-6 hoisted the CLI runtime helpers and the 5 per-CLI
chat executors out of ``workflows.py``, this file pins the new public
import shape and the legacy alias contract:

  1. ``cli_runtime`` exposes ``run_cli_with_heartbeat`` and
     ``safe_cli_error_snippet`` as top-level callables.
  2. Each per-platform executor is importable from its own
     ``cli_executors.<platform>`` submodule under the
     ``execute_<platform>_chat`` name.
  3. The ``cli_executors`` package re-exports those 5 names at the
     top level for ergonomic imports.
  4. ``workflows.py`` keeps the legacy ``_<platform>_chat`` /
     ``_run_cli_with_heartbeat`` / ``_safe_cli_error_snippet`` /
     ``_opencode_sessions`` aliases pointing at the same object so
     production callers and existing test patches continue to resolve
     via ``workflows._foo`` with object-identity (``is``) preserved.
"""
from __future__ import annotations


def test_cli_runtime_public_surface():
    """cli_runtime exposes the heartbeat wrapper and the JSONL-safe
    error-snippet helper as top-level callables."""
    import cli_runtime

    assert callable(cli_runtime.run_cli_with_heartbeat)
    assert callable(cli_runtime.safe_cli_error_snippet)


def test_per_platform_executor_imports():
    """Each per-platform executor is importable from its own submodule
    under the ``execute_<platform>_chat`` public name."""
    from cli_executors.claude import execute_claude_chat
    from cli_executors.codex import execute_codex_chat
    from cli_executors.copilot import execute_copilot_chat
    from cli_executors.gemini import execute_gemini_chat
    from cli_executors.opencode import execute_opencode_chat

    for fn in (
        execute_claude_chat,
        execute_codex_chat,
        execute_copilot_chat,
        execute_gemini_chat,
        execute_opencode_chat,
    ):
        assert callable(fn)


def test_cli_executors_package_reexports():
    """The ``cli_executors`` package re-exports all 5 executors at the
    top level so callers can do ``from cli_executors import …``."""
    import cli_executors

    expected = {
        "execute_claude_chat",
        "execute_codex_chat",
        "execute_copilot_chat",
        "execute_gemini_chat",
        "execute_opencode_chat",
    }
    assert expected.issubset(set(cli_executors.__all__))
    for name in expected:
        assert callable(getattr(cli_executors, name))


def test_workflows_legacy_aliases_still_resolve():
    """Production callers and most existing test patches resolve the
    moved helpers via the legacy underscore-prefixed names on the
    ``workflows`` module. These re-exports must preserve object identity
    so monkeypatches and ``is``-checks continue to work."""
    import cli_runtime
    import workflows as wf
    from cli_executors.claude import execute_claude_chat
    from cli_executors.codex import execute_codex_chat
    from cli_executors.copilot import execute_copilot_chat
    from cli_executors.gemini import execute_gemini_chat
    from cli_executors.opencode import (
        execute_opencode_chat,
        _execute_opencode_chat_cli,
        _opencode_sessions,
        OPENCODE_OLLAMA_URL,
        OPENCODE_MODEL,
        OPENCODE_PORT,
    )

    # cli_runtime helpers — re-exported under the old `_`-prefixed names.
    assert wf._run_cli_with_heartbeat is cli_runtime.run_cli_with_heartbeat
    assert wf._safe_cli_error_snippet is cli_runtime.safe_cli_error_snippet

    # Per-platform chat executors — same object on both sides.
    assert wf._execute_claude_chat is execute_claude_chat
    assert wf._execute_codex_chat is execute_codex_chat
    assert wf._execute_copilot_chat is execute_copilot_chat
    assert wf._execute_gemini_chat is execute_gemini_chat
    assert wf._execute_opencode_chat is execute_opencode_chat

    # OpenCode internal symbols — passthrough re-exports preserving
    # the same dict / function object so callers mutating
    # `wf._opencode_sessions` see effects in `cli_executors.opencode`.
    assert wf._execute_opencode_chat_cli is _execute_opencode_chat_cli
    assert wf._opencode_sessions is _opencode_sessions
    assert wf.OPENCODE_OLLAMA_URL == OPENCODE_OLLAMA_URL
    assert wf.OPENCODE_MODEL == OPENCODE_MODEL
    assert wf.OPENCODE_PORT == OPENCODE_PORT
