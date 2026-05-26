"""Pydantic models for Luna Learn from Media subsystem."""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class LearningIntent(BaseModel):
    """A request to learn from media. Either source_url or attachment_path required."""
    source_url: str | None = None
    attachment_path: str | None = None
    tenant_id: str
    actor_user_id: str
    resume_job_id: str | None = None
    dry_run: bool = False

    @model_validator(mode="after")
    def _one_of_url_or_attachment(self) -> "LearningIntent":
        if not self.source_url and not self.attachment_path and not self.resume_job_id:
            raise ValueError("source_url, attachment_path, or resume_job_id required")
        return self


class SkillDraft(BaseModel):
    skill_md: str
    slug: str
    engine: str
    synthetic_test_input: dict
    synthetic_test_expected: dict


class ReviewVerdict(str, Enum):
    APPROVED = "approved"
    REVISE = "revise"
    REJECTED = "rejected"


class ReviewResult(BaseModel):
    verdict: ReviewVerdict
    findings: list[str] = Field(default_factory=list)
    reviewer_agent_id: str


class TestResult(BaseModel):
    passed: bool
    actual_output: dict | None = None
    error: str | None = None


class LearningJobState(BaseModel):
    """Persisted cache state for --resume-last."""
    job_id: str
    source_url: str | None
    transcript: str | None = None
    draft: SkillDraft | None = None
    last_review: ReviewResult | None = None
    last_test: TestResult | None = None
