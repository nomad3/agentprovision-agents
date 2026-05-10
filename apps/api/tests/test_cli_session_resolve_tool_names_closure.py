"""Regression test for the closure-binding bug that silently disabled Luna
WhatsApp dispatch.

History
-------
Commit ``6494ae61`` (Phase 4 — leaf-MCP auth tier) added a redundant local
``from app.services.tool_groups import resolve_tool_names`` inside an
``if use_resilient:`` branch of ``_run_agent_session_legacy``. Python's
static scope analysis turned ``resolve_tool_names`` into a function-local
in the *enclosing* function — visible in the outer's ``co_cellvars``.
The nested async closure ``_run_workflow`` defined further down then
captured it as a free variable (its ``co_freevars`` included
``resolve_tool_names``) instead of doing a module-global lookup. When
``use_resilient`` was False (the common case for Luna in WhatsApp) the
local was never bound and the closure raised::

    NameError: cannot access free variable 'resolve_tool_names' where it
    is not associated with a value in enclosing scope

Effect: every WhatsApp message into Luna fell through ``ChatCliWorkflow
dispatch failed`` and never reached an agent. Worse, the ``except`` that
caught the NameError didn't ROLLBACK the SQL session, so the connection
was poisoned with ``InFailedSqlTransaction`` for every subsequent query.

This test pins the bytecode-level fix in place: ``_run_workflow``'s
``resolve_tool_names`` lookup must NOT appear in either the outer's
``co_cellvars`` or the inner's ``co_freevars`` — only ``co_names``,
which is the LOAD_GLOBAL slot pointing at the module-level import.

The trick is that the analysis must compile the *whole module* — not
just the closure in isolation — because Python's scope rules depend on
what the enclosing function does. An earlier version of this test
compiled ``_run_workflow`` standalone and missed the bug entirely.
"""
from __future__ import annotations

import os


def _walk_consts(code, target_name):
    """Yield every code object in ``code.co_consts`` (recursively) whose
    ``co_name`` matches ``target_name``."""
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            if const.co_name == target_name:
                yield const
            yield from _walk_consts(const, target_name)


def _module_code():
    """Compile cli_session_manager.py as a module and return the code
    object. Compiling the whole module preserves the lexical-scope
    relationship between ``_run_agent_session_legacy`` and the nested
    ``_run_workflow`` closure, which is what the test needs to verify.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(here, "app", "services", "cli_session_manager.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    return compile(src, src_path, "exec")


def _find_outer():
    mod_code = _module_code()
    outers = list(_walk_consts(mod_code, "_run_agent_session_legacy"))
    assert len(outers) == 1, (
        f"expected exactly one _run_agent_session_legacy code object, "
        f"got {len(outers)}"
    )
    return outers[0]


def _find_inner_workflow():
    outer = _find_outer()
    inners = list(_walk_consts(outer, "_run_workflow"))
    assert len(inners) == 1, (
        f"expected exactly one nested _run_workflow inside "
        f"_run_agent_session_legacy, got {len(inners)}"
    )
    return outer, inners[0]


def test_outer_does_not_capture_resolve_tool_names_for_closure():
    """The enclosing function must NOT mark resolve_tool_names as a cell
    variable. Any local assignment (including ``from X import Y``) of
    that name in the enclosing function body would land here.
    """
    outer = _find_outer()
    assert "resolve_tool_names" not in outer.co_cellvars, (
        "_run_agent_session_legacy is exposing resolve_tool_names as a "
        "cell variable. A redundant local re-import was reintroduced — "
        "see the file docstring for the production failure mode."
    )


def test_inner_workflow_does_not_capture_resolve_tool_names_as_freevar():
    """The closure must NOT see resolve_tool_names in its co_freevars.
    A captured freevar means the lookup will fail with a NameError when
    the cell is unbound, which is exactly the production bug.
    """
    _outer, inner = _find_inner_workflow()
    assert "resolve_tool_names" not in inner.co_freevars, (
        "_run_workflow is capturing resolve_tool_names from the "
        "enclosing scope. The closure will fail at runtime when the "
        "cell is unbound — which is what happens for use_resilient=False."
    )


def test_inner_workflow_resolves_resolve_tool_names_as_global():
    """The closure must look up resolve_tool_names via LOAD_GLOBAL —
    landing on the module-scope import at the top of the file.
    """
    _outer, inner = _find_inner_workflow()
    assert "resolve_tool_names" in inner.co_names, (
        "_run_workflow does not look up resolve_tool_names via "
        "LOAD_GLOBAL. Either the closure stopped using it (delete this "
        "test) or scope rules changed."
    )
