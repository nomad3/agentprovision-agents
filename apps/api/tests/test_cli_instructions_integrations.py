"""Pin the `## Connected Integrations` section in the CLI CLAUDE.md.

Bug history (2026-05-04): the agent kept telling the user "I don't
have permission to access Gmail" / "please re-authorize" even though
the tenant had 204 active gmail credentials. Root cause:
generate_cli_instructions never injected the list of enabled
integrations into the agent's CLAUDE.md, so models had no positive
signal that gmail / calendar / github were actually wired up — they
defaulted to the safer "ask the user to (re)authorize" path.

These tests pin:
- The section appears when integrations exist
- Account emails land in the rendered output
- Disabled rows are filtered out
- Duplicate (name, email) pairs are de-duplicated
- The section is omitted entirely when no integrations are connected
  (so we don't render an empty header that would itself be misleading)
- The function is exception-tolerant — bad input shouldn't crash chat
"""
from app.services.cli_session_manager import generate_cli_instructions


def _base_kwargs():
    return dict(
        skill_body="",
        tenant_name="acme",
        user_name="Simon",
        channel="web",
        conversation_summary="",
        memory_context={},
    )


def test_section_appears_when_integrations_present():
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            {"integration_name": "gmail", "account_email": "user@example.com", "enabled": True},
        ],
    )
    assert "## Connected Integrations" in out
    assert "gmail" in out
    assert "user@example.com" in out


def test_section_is_omitted_when_no_integrations():
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[],
    )
    assert "## Connected Integrations" not in out


def test_section_is_omitted_when_param_is_none():
    out = generate_cli_instructions(**_base_kwargs())  # no connected_integrations kwarg
    assert "## Connected Integrations" not in out


def test_disabled_rows_are_filtered_out():
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            {"integration_name": "gmail", "account_email": "live@example.com", "enabled": True},
            {"integration_name": "github", "account_email": "stale@example.com", "enabled": False},
        ],
    )
    assert "live@example.com" in out
    # Disabled row should NOT contribute to the rendered list
    assert "stale@example.com" not in out


def test_duplicate_name_email_pairs_are_deduped():
    """Multiple integration_credentials rows for the same
    (integration_name, account_email) shouldn't produce duplicate
    bullets in the agent's prompt."""
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            {"integration_name": "gmail", "account_email": "u@example.com", "enabled": True},
            {"integration_name": "gmail", "account_email": "u@example.com", "enabled": True},
            {"integration_name": "gmail", "account_email": "u@example.com", "enabled": True},
        ],
    )
    # Exactly one bullet for that pair
    assert out.count("`u@example.com`") == 1


def test_no_email_renders_just_the_integration_name():
    """Some integrations don't carry an account_email (e.g. Slack
    workspace tokens). Those should still render — just without the
    `account: ...` suffix."""
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            {"integration_name": "slack", "account_email": None, "enabled": True},
        ],
    )
    assert "slack" in out
    assert "account:" not in out.split("## Connected Integrations", 1)[1].split("##", 1)[0]


def test_tolerates_bad_rows():
    """Defensive: the chat hot path must never crash because of one
    malformed row. Strings, missing keys, non-dicts — all skipped."""
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            "not-a-dict",
            None,
            {},
            {"integration_name": "gmail", "account_email": "good@example.com", "enabled": True},
        ],
    )
    assert "good@example.com" in out


def test_instructs_agent_to_proceed_directly():
    """The header copy is load-bearing — it explicitly tells the agent
    to skip the (re)authorize prompt for connected integrations.
    Pinning so a future prompt cleanup doesn't accidentally weaken
    this instruction back into the original bug."""
    out = generate_cli_instructions(
        **_base_kwargs(),
        connected_integrations=[
            {"integration_name": "gmail", "account_email": "u@e.com", "enabled": True},
        ],
    )
    assert "CONNECTED" in out  # positive signal
    assert "proceed directly" in out  # explicit instruction
