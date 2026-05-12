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


@pytest.mark.parametrize("kind", ["github_pr", "github_issue", "quickstart-stub"])
def test_recognised_kinds_not_persisted(kind):
    """Deferred-by-design kinds return 'recognised' without inserting.
    Reviewer (PR #408 finding #4): contract verification."""
    item = {"kind": kind, "title": "anything"}
    outcome, captured = _run(item)
    assert outcome == "recognised"
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
