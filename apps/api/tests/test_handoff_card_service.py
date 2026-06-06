"""Tests for PR 3 handoff-card service helpers (render for PR/issue + summary)."""
from app.schemas.handoff_card import HandoffCard
from app.services.handoff_card import render_markdown, summary_line


def _card():
    return HandoffCard(
        tenant_id="t1",
        from_agent="luna",
        to_agent="claudia",
        objective="Add source-grounding labels",
        system="agentprovision-agents",
        source_docs=["docs/plans/trusted-teammate.md"],
        constraints=["trace-only", "no hot-path wiring"],
        non_goals=["do not block actions"],
        expected_artifact="PR with schema + service + tests",
        reviewer_focus=["evidence-before-interpretation invariant"],
        stop_conditions=["tests fail", "scope grows beyond the schema"],
        created_at="2026-06-06T05:00:00Z",
    )


def test_summary_line_is_one_line_with_direction_and_objective():
    s = summary_line(_card())
    assert "\n" not in s
    assert "luna" in s.lower()
    assert "claudia" in s.lower()
    assert "Add source-grounding labels" in s


def test_render_markdown_contains_every_section():
    md = render_markdown(_card())
    for heading in [
        "Objective", "System", "Source docs", "Constraints",
        "Non-goals", "Expected artifact", "Reviewer focus", "Stop conditions",
    ]:
        assert heading in md, f"missing section: {heading}"


def test_render_markdown_renders_list_items_as_bullets():
    md = render_markdown(_card())
    assert "- trace-only" in md
    assert "- tests fail" in md
    assert "- evidence-before-interpretation invariant" in md


def test_render_markdown_is_attachable_to_a_pr_body():
    md = render_markdown(_card())
    # starts with a markdown header so it drops cleanly into a PR body/comment
    assert md.lstrip().startswith("#")
    # names the handoff direction so a reviewer sees the contract owner
    assert "luna" in md.lower() and "claudia" in md.lower()


def test_empty_list_section_renders_a_none_placeholder_not_a_crash():
    # non_goals can legitimately be empty; rendering must not break.
    card = HandoffCard(
        tenant_id="t1", from_agent="luna", to_agent="claudia",
        objective="x", system="repo", source_docs=[], constraints=[],
        non_goals=[], expected_artifact="y",
        reviewer_focus=["focus"], stop_conditions=["stop"],
        created_at="2026-06-06T05:00:00Z",
    )
    md = render_markdown(card)
    assert "Non-goals" in md
    assert "_none_" in md
