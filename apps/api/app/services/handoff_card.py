"""Handoff-card service helpers — PR 3 trusted-teammate engines.

Stateless rendering for a `HandoffCard`:

  - ``summary_line`` — a one-line description so a receiver (or a PR title)
    can see the handoff direction + objective at a glance.
  - ``render_markdown`` — a markdown block that drops cleanly into a GitHub PR
    body or issue comment, so the card doubles as the review contract.

Pure functions, no IO, not wired into any runtime path.
"""
from __future__ import annotations

from typing import List

from app.schemas.handoff_card import HandoffCard


def summary_line(card: HandoffCard) -> str:
    """One-line handoff description (direction + objective + system)."""
    return (
        f"Handoff {card.from_agent} → {card.to_agent}: "
        f"{card.objective} [{card.system}]"
    )


def _bullets(items: List[str]) -> str:
    if not items:
        return "_none_"
    return "\n".join(f"- {item}" for item in items)


def render_markdown(card: HandoffCard) -> str:
    """Render the card as markdown for a GitHub PR body or issue comment.

    The block doubles as the review contract: Reviewer focus and Stop
    conditions are first-class sections a Code Reviewer can cite.
    """
    return "\n".join([
        f"# Handoff: {card.from_agent} → {card.to_agent}",
        "",
        f"**Objective:** {card.objective}",
        f"**System:** {card.system}",
        "",
        "## Source docs",
        _bullets(card.source_docs),
        "",
        "## Constraints",
        _bullets(card.constraints),
        "",
        "## Non-goals",
        _bullets(card.non_goals),
        "",
        "## Expected artifact",
        card.expected_artifact,
        "",
        "## Reviewer focus",
        _bullets(card.reviewer_focus),
        "",
        "## Stop conditions",
        _bullets(card.stop_conditions),
        "",
        f"_Handoff created {card.created_at} · tenant {card.tenant_id}_",
    ])


__all__ = ["summary_line", "render_markdown"]
