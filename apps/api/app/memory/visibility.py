"""Visibility filter for multi-agent scoping. Used by recall queries.

Phase 1.3 stub: pass-through. Plan Task 11 replaces this with a real
filter that scopes rows by `visibility` (`tenant_wide` | `agent_group` |
`agent_only`) and `visible_to` (list of agent slugs) on the model.

The signature is locked: `apply_visibility(query, model, agent_slug)`.
Task 11 must NOT change the signature — only the body.
"""
from __future__ import annotations

from typing import Any


def apply_visibility(query: Any, model: Any, agent_slug: str) -> Any:
    """Pass-through stub. Returns the query unchanged.

    TODO(Task 11): apply visibility filter:
        - tenant_wide rows: visible to all agents
        - agent_only rows: visible only to owner_agent_slug == agent_slug
        - agent_group rows: visible if agent_slug in visible_to
    """
    return query
