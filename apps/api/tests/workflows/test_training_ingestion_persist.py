"""Tests for `_persist_item` in TrainingIngestionWorkflow (PR-Q4).

Reviewer NIT #9 (PR #408): the rule dispatcher is pure-logic + a
service call; table-driven tests are cheap and pin the wire-format
contract between Q3a/Q3b scanners and the Q4 extractor.

We mock `create_entity` to a pass-through that captures the
KnowledgeEntityCreate payload, and `_existing_entity_id` to control
the dedup outcome per test case. This keeps the tests free of a
live DB session.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sqlalchemy")

from app.workflows.training_ingestion import _persist_item


# ── helpers ──────────────────────────────────────────────────────────


def _mock_db():
    """Return a MagicMock that satisfies `_persist_item`'s shape:
    queries return None (no dedup match) by default; `create_entity`
    appends to a captured list.
    """
    db = MagicMock()
    return db


def _run(item, *, existing_id=None):
    """Invoke `_persist_item` with `_existing_entity_id` patched to
    return `existing_id` (None = no dedup match) and `create_entity`
    patched to capture the payload.

    Returns (outcome, captured_payloads).
    """
    captured: list = []

    def _capture(_db, ent, _tenant_id):
        captured.append(ent)

    # _persist_item imports `create_entity` lazily INSIDE its body, so
    # the patch target is the source module — not training_ingestion.
    with patch(
        "app.workflows.training_ingestion._existing_entity_id",
        return_value=existing_id,
    ), patch(
        "app.services.knowledge.create_entity",
        new=_capture,
    ):
        outcome = _persist_item(_mock_db(), MagicMock(), item)
    return outcome, captured


def _run_with_observation(item, *, existing_id=None):
    """Variant of `_run` for the github_pr/github_issue branch
    (PR-Q3a-back-2): patches `create_observation` instead of
    `create_entity` and returns (outcome, captured_observation_calls).

    Each captured call is the kwargs dict so tests can assert on
    `entity_id`, `observation_text`, `source_ref`, etc.
    """
    captured: list = []

    def _capture(_db, **kwargs):
        captured.append(kwargs)

    # Same lazy-import quirk — patch at the source module.
    with patch(
        "app.workflows.training_ingestion._existing_entity_id",
        return_value=existing_id,
    ), patch(
        "app.services.knowledge.create_observation",
        new=_capture,
    ):
        outcome = _persist_item(_mock_db(), MagicMock(), item)
    return outcome, captured


# ── recognised kinds ─────────────────────────────────────────────────


def test_local_user_identity_creates_person():
    item = {"kind": "local_user_identity", "name": "Alice", "email": "a@x.com"}
    outcome, captured = _run(item)
    assert outcome == "persisted"
    assert len(captured) == 1
    ent = captured[0]
    assert ent.entity_type == "person"
    assert ent.category == "user"
    assert ent.name == "Alice"
    assert ent.attributes["email"] == "a@x.com"
    assert ent.attributes["source"] == "ap_quickstart_local_ai_cli"


def test_local_user_identity_falls_back_to_email_for_name():
    item = {"kind": "local_user_identity", "email": "noname@x.com"}
    outcome, captured = _run(item)
    assert outcome == "persisted"
    assert captured[0].name == "noname@x.com"


def test_local_user_identity_skips_when_email_already_persisted():
    """Dedup hit on the email attribute → skip insert + return 'persisted'."""
    item = {"kind": "local_user_identity", "name": "Alice", "email": "a@x.com"}
    outcome, captured = _run(item, existing_id="some-uuid")
    assert outcome == "persisted"
    assert captured == []  # no insert because dedup returned an id


def test_local_ai_session_creates_project_with_basename():
    item = {
        "kind": "local_ai_session",
        "project_path": "/Users/x/code/myproject",
        "runtime": "claude_code",
        "derived_topic_hint": "fix the build",
    }
    outcome, captured = _run(item)
    assert outcome == "persisted"
    ent = captured[0]
    assert ent.entity_type == "project"
    assert ent.name == "myproject"
    assert ent.description == "fix the build"
    assert ent.attributes["project_path"] == "/Users/x/code/myproject"
    assert ent.attributes["runtime"] == "claude_code"


def test_local_ai_session_without_project_path_is_recognised_not_persisted():
    item = {"kind": "local_ai_session", "runtime": "codex"}
    outcome, captured = _run(item)
    assert outcome == "recognised"
    assert captured == []  # nothing to anchor a project on


def test_local_ai_session_dedups_on_project_path():
    item = {"kind": "local_ai_session", "project_path": "/Users/x/repo"}
    outcome, captured = _run(item, existing_id="existing-uuid")
    assert outcome == "persisted"
    assert captured == []


def test_github_user_creates_person_with_bio_description():
    item = {
        "kind": "github_user",
        "login": "alice",
        "name": "Alice Doe",
        "email": "alice@x.com",
        "bio": "rust + python",
        "company": "@acme",
        "location": "SF",
    }
    outcome, captured = _run(item)
    assert outcome == "persisted"
    ent = captured[0]
    assert ent.entity_type == "person"
    assert ent.description == "rust + python"  # bio, NOT email (NIT #8)
    assert ent.attributes["github_login"] == "alice"
    assert ent.attributes["email"] == "alice@x.com"


def test_github_user_dedups_on_github_login():
    item = {"kind": "github_user", "login": "alice"}
    outcome, captured = _run(item, existing_id="x")
    assert outcome == "persisted"
    assert captured == []


def test_github_repo_creates_project_with_html_url():
    item = {
        "kind": "github_repo",
        "name": "myrepo",
        "full_name": "alice/myrepo",
        "owner": "alice",  # flattened from {login: alice} by Q3b
        "language": "Rust",
        "html_url": "https://github.com/alice/myrepo",
        "private": False,
    }
    outcome, captured = _run(item)
    assert outcome == "persisted"
    ent = captured[0]
    assert ent.entity_type == "project"
    assert ent.source_url == "https://github.com/alice/myrepo"
    assert ent.attributes["owner"] == "alice"
    assert ent.attributes["full_name"] == "alice/myrepo"
    assert ent.attributes["language"] == "Rust"


def test_github_repo_dedups_on_full_name():
    item = {"kind": "github_repo", "full_name": "alice/repo"}
    outcome, captured = _run(item, existing_id="x")
    assert outcome == "persisted"
    assert captured == []


def test_github_org_creates_organization():
    item = {"kind": "github_org", "login": "acme", "description": "we make widgets"}
    outcome, captured = _run(item)
    assert outcome == "persisted"
    ent = captured[0]
    assert ent.entity_type == "organization"
    assert ent.category == "organization"
    assert ent.name == "acme"


def test_github_org_dedups_on_login_name():
    item = {"kind": "github_org", "login": "acme"}
    outcome, captured = _run(item, existing_id="x")
    assert outcome == "persisted"
    assert captured == []


# ── recognised-but-deferred kinds ────────────────────────────────────


def test_quickstart_stub_is_recognised_not_persisted():
    """Stub items from Q5 server-side bootstrappers that don't have
    real collectors yet must surface as 'recognised' so the user-
    visible progress bar advances honestly. Reviewer (PR #408 finding
    #4): contract verification."""
    outcome, captured = _run({"kind": "quickstart-stub", "channel": "gmail"})
    assert outcome == "recognised"
    assert captured == []


# ── github_pr / github_issue → observations on parent repo (Q3a-back-2)


def test_github_pr_creates_observation_on_parent_repo():
    """Q3a-back-2: PR items land as free-text observations on the
    Project entity persisted by the same snapshot's github_repo
    branch — NOT as standalone entities (one-entity-per-PR drowns
    recall ranking)."""
    item = {
        "kind": "github_pr",
        "title": "Fix the cascade",
        "state": "merged",
        "url": "https://github.com/nomad3/repo/pull/42",
        "repository": "nomad3/repo",
    }
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "persisted"
    assert len(captured) == 1
    obs = captured[0]
    # text shape: "PR: <title> (<state>)" — the human-readable pair
    # that recall ranks against. URL goes in source_ref to keep the
    # text compact.
    assert "PR" in obs["observation_text"]
    assert "Fix the cascade" in obs["observation_text"]
    assert "merged" in obs["observation_text"]
    assert obs["source_ref"] == "https://github.com/nomad3/repo/pull/42"
    assert obs["entity_id"] == "parent-uuid"
    assert obs["source_channel"] == "ap_quickstart_github_cli"
    assert obs["source_platform"] == "github"


def test_github_issue_creates_observation_on_parent_repo():
    """Issues take the same path as PRs, just with the `Issue:` prefix
    so the observation text reads naturally."""
    item = {
        "kind": "github_issue",
        "title": "Document the cascade fix",
        "state": "open",
        "url": "https://github.com/nomad3/repo/issues/17",
        "repository": "nomad3/repo",
    }
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "persisted"
    assert len(captured) == 1
    obs = captured[0]
    assert obs["observation_text"].startswith("Issue:")
    assert "Document the cascade fix" in obs["observation_text"]
    assert "open" in obs["observation_text"]


def test_github_pr_without_parent_repo_is_recognised_not_persisted():
    """User has gh access to a PR on a repo we don't track (public
    review, cross-org collab). Orphan observations with no entity_id
    poison recall, so skip the create_observation call and return
    'recognised' — the user-visible bar still advances."""
    item = {
        "kind": "github_pr",
        "title": "Some external review",
        "state": "open",
        "url": "https://github.com/other-org/other-repo/pull/1",
        "repository": "other-org/other-repo",
    }
    outcome, captured = _run_with_observation(item, existing_id=None)
    assert outcome == "recognised"
    assert captured == []


def test_github_issue_without_parent_repo_is_recognised_not_persisted():
    """Same orphan-skip rule as PRs."""
    item = {
        "kind": "github_issue",
        "title": "External issue",
        "state": "closed",
        "url": "https://github.com/other-org/other-repo/issues/9",
        "repository": "other-org/other-repo",
    }
    outcome, captured = _run_with_observation(item, existing_id=None)
    assert outcome == "recognised"
    assert captured == []


@pytest.mark.parametrize("kind", ["github_pr", "github_issue"])
def test_github_pr_issue_missing_repository_is_unknown(kind):
    """The Q3b scanner ALWAYS sets `repository` (nameWithOwner). A
    missing value is wire-format drift — bucket it as 'unknown' so
    the per-batch WARN histogram surfaces the schema break instead
    of silently inflating the recognised counter."""
    item = {"kind": kind, "title": "no repo field", "state": "open"}
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "unknown"
    assert captured == []


@pytest.mark.parametrize("kind", ["github_pr", "github_issue"])
def test_github_pr_issue_empty_title_and_state_is_unknown(kind):
    """Reviewer I1 (PR #413, 2026-05-12): an item with empty title AND
    empty state would auto-embed to a bare 'PR' or 'Issue' near-stop-
    word vector. Every untitled-stateless item from the tenant would
    then recall-match every other one, poisoning the ranker. The Q3b
    scanner contract guarantees a non-empty title (gh always returns
    one), so a missing pair is wire-format drift — route it through
    'unknown' so the per-batch WARN histogram surfaces it instead."""
    item = {
        "kind": kind,
        "title": "",
        "state": "",
        "url": "https://x/y",
        "repository": "nomad3/repo",
    }
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "unknown"
    assert captured == []


@pytest.mark.parametrize("kind", ["github_pr", "github_issue"])
def test_github_pr_issue_empty_title_with_state_still_creates_observation(kind):
    """State-only is acceptable signal — the resulting 'PR (merged)' or
    'Issue (open)' text still differentiates between observations,
    even if it's not as informative as a titled version. Only the
    empty-empty pair is the recall-poisoning case."""
    item = {
        "kind": kind,
        "title": "",
        "state": "merged",
        "url": "https://x/y/1",
        "repository": "nomad3/repo",
    }
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "persisted"
    assert len(captured) == 1
    # State token must be present so vectors stay distinct.
    assert "merged" in captured[0]["observation_text"]


def test_github_pr_with_non_string_repository_is_unknown():
    """Defense against an scanner shipping a non-string repository
    (e.g. a struct it forgot to flatten). The isinstance check on the
    activity side bucket-routes this to 'unknown' instead of crashing
    on the JSONB `->>` lookup."""
    item = {
        "kind": "github_pr",
        "title": "weird shape",
        "state": "open",
        "repository": {"unexpected": "nested"},
    }
    outcome, captured = _run_with_observation(item, existing_id="parent-uuid")
    assert outcome == "unknown"
    assert captured == []


# ── unknown kinds ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kind", ["", "<missing>", "future_wedge", "totally-unknown", "github_release"]
)
def test_unknown_kinds_return_unknown(kind):
    """Anything not in the rule table must surface as 'unknown' so the
    activity body can route it into the per-batch WARN histogram."""
    item = {"kind": kind} if kind else {}
    outcome, captured = _run(item)
    assert outcome == "unknown"
    assert captured == []
