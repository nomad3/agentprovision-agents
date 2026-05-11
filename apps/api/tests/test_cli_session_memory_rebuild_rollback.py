"""Regression test for the rebuild-fallback rollback fix.

When `pre_built_memory_context` is not passed to `_run_agent_session_legacy`
(the "should not happen in normal flow" branch at line 887), the function
falls back to `build_memory_context_with_git`. That call hits the same
pgvector + entity-table queries as the router-side path. If any of them
fail — earlier txn already aborted, asyncpg NULL coerce, etc. — psycopg2
leaves the session in a poisoned state.

Before this fix, the `except Exception` at line 902 caught the error, set
`memory_context = {}`, and continued. The very next ORM query in the
dispatch (mcp_server_connectors load) then failed with
`psycopg2.errors.InFailedSqlTransaction: current transaction is aborted`.

This was the recurring 56-error/hour cascade we saw on the orchestration
worker logs after PRs #349/#352/#361 closed the other catch sites — this
was the last one missing a rollback.

Sibling tests live in `tests/test_cli_dispatch_rollback_safety.py` (PR
#352). Same pattern: a sqlite-backed `_RollbackTrackingSession` that
records rollback calls + asserts a follow-up `SELECT 1` succeeds after
the synthetic failure.
"""
from __future__ import annotations

import ast
import os


def _module_code():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(here, "app", "services", "cli_session_manager.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    return src


def test_rebuild_fallback_except_branch_calls_safe_rollback():
    """The rebuild-fallback `except` at the "Memory context not pre-built"
    site MUST call `safe_rollback(db)` to drain a poisoned transaction.
    Without it, the dispatch cascades into `InFailedSqlTransaction` on
    every subsequent query.
    """
    src = _module_code()
    tree = ast.parse(src)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # Match the rebuild try: body should reference build_memory_context_with_git
        body_unparse = "\n".join(ast.unparse(n) for n in node.body)
        if "build_memory_context_with_git" not in body_unparse:
            continue
        # Match the rebuild handler: must contain a warning logger AND
        # the literal substring "Memory recall failed" (not the router
        # "Memory context build failed" form — they're sister sites).
        handler_unparse = "\n".join(
            ast.unparse(h) for h in node.handlers
        )
        if "Memory recall failed" not in handler_unparse:
            continue
        found = True
        assert "safe_rollback" in handler_unparse, (
            "rebuild-fallback handler does not call safe_rollback(db). "
            "Without it, the dispatch txn stays poisoned and every "
            "subsequent ORM query (mcp_server_connectors, agent_tasks, "
            "cli_sessions) cascades into InFailedSqlTransaction. See "
            "the module docstring for the production failure mode."
        )

    assert found, (
        "rebuild-fallback try/except block not located in "
        "cli_session_manager.py. The handler shape changed — update this "
        "regression test to match."
    )


def test_safe_rollback_is_imported():
    """Sanity check: the module imports safe_rollback at module scope.
    Avoids the closure-shadowing bug we fixed in PR #349 — a local
    re-import would mark the symbol as a function-local in the enclosing
    scope, breaking the nested `_run_workflow` closure that references it.
    """
    src = _module_code()
    assert "from app.db.safe_ops import safe_rollback" in src, (
        "safe_rollback is not imported at module scope. If you moved it "
        "into a function body, fix that — see PR #349 for why."
    )
