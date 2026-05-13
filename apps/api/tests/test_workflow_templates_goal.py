"""Goal recipe template seed assertions.

Locks the contract the `alpha goal` CLI command depends on:
  * the template is named "Goal" with tier="native" (the CLI resolves
    by (name, tier) since the UUID is per-tenant after install);
  * the single agent step's prompt interpolates every contract slot
    (outcome / success_criteria / operating_rules / quality_bar /
    deliverable) so a slot rename in the CLI without a matching
    workflow_templates update can't silently ship.

Counterpart to apps/agentprovision-cli/src/commands/goal.rs.
"""

from app.services.workflow_templates import NATIVE_TEMPLATES


def _goal_template():
    matches = [t for t in NATIVE_TEMPLATES if t["name"] == "Goal"]
    assert len(matches) == 1, "exactly one Goal template must be seeded"
    return matches[0]


def test_goal_template_is_native_and_public():
    tmpl = _goal_template()
    assert tmpl["tier"] == "native"
    assert tmpl["public"] is True
    # Tags must include "goal" because `alpha recipes ls --tag goal` is
    # a documented discovery path.
    assert "goal" in tmpl["tags"]


def test_goal_template_trigger_is_manual():
    # Goals are user-initiated; no cron or event fan-in.
    assert _goal_template()["trigger_config"] == {"type": "manual"}


def test_goal_template_has_single_agent_step():
    defn = _goal_template()["definition"]
    assert "steps" in defn
    assert len(defn["steps"]) == 1
    step = defn["steps"][0]
    assert step["type"] == "agent"
    # The agent is "luna" — same default as every other native template.
    # Changing this MUST be a deliberate design decision, not drift.
    assert step["agent"] == "luna"


def test_goal_prompt_interpolates_every_contract_slot():
    # If the CLI renames a slot, this test fails — preventing the
    # silent "the prompt still renders, but with {{input.foo}} blank"
    # failure mode.
    step = _goal_template()["definition"]["steps"][0]
    prompt = step["prompt"]
    for slot in (
        "input.outcome",
        "input.success_criteria",
        "input.operating_rules",
        "input.quality_bar",
        "input.deliverable",
    ):
        assert "{{" + slot + "}}" in prompt, f"missing {{{{ {slot} }}}} in goal prompt"


def test_goal_prompt_enforces_done_contract():
    # Sanity check on the non-trivial part of the contract: the agent
    # is told to STOP rather than silently relax a criterion. Without
    # this, the recipe's value collapses to "an agent with a prompt".
    prompt = _goal_template()["definition"]["steps"][0]["prompt"]
    assert "must satisfy every success criterion" in prompt.lower()
    assert "needs_input" in prompt
