import pytest
from app.schemas.learning import (
    LearningIntent, SkillDraft, ReviewVerdict, ReviewResult,
    TestResult, LearningJobState,
)


def test_learning_intent_url():
    intent = LearningIntent(source_url="https://youtu.be/abc123", tenant_id="t1", actor_user_id="u1")
    assert intent.source_url == "https://youtu.be/abc123"


def test_learning_intent_attachment():
    intent = LearningIntent(attachment_path="/tmp/x.mp4", tenant_id="t1", actor_user_id="u1")
    assert intent.attachment_path == "/tmp/x.mp4"


def test_learning_intent_requires_url_or_attachment():
    with pytest.raises(ValueError):
        LearningIntent(tenant_id="t1", actor_user_id="u1")


def test_skill_draft_has_test_payload():
    d = SkillDraft(
        skill_md="---\nname: foo\nengine: markdown\n---\nbody",
        slug="foo", engine="markdown",
        synthetic_test_input={"x": 1}, synthetic_test_expected={"y": 2},
    )
    assert d.engine == "markdown"


def test_review_verdict_values():
    assert {ReviewVerdict.APPROVED, ReviewVerdict.REVISE, ReviewVerdict.REJECTED}
