import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_test_suite import AgentTestCase, AgentTestRun

logger = logging.getLogger(__name__)


def _score_case(actual_text: str, quality_score: Optional[float], latency_ms: int, case: AgentTestCase) -> dict:
    """Evaluate a single case; returns {pass, reason, ...}."""
    reasons = []
    text_lower = (actual_text or "").lower()

    for needle in case.expected_output_contains or []:
        if str(needle).lower() not in text_lower:
            reasons.append(f"missing expected phrase: {needle}")

    for banned in case.expected_output_excludes or []:
        if str(banned).lower() in text_lower:
            reasons.append(f"contains banned phrase: {banned}")

    min_quality = float(case.min_quality_score or 0)
    if quality_score is not None and quality_score < min_quality:
        reasons.append(f"quality {quality_score:.2f} below minimum {min_quality:.2f}")

    max_latency = int(case.max_latency_ms or 0)
    if max_latency > 0 and latency_ms > max_latency:
        reasons.append(f"latency {latency_ms}ms exceeds max {max_latency}ms")

    return {
        "case_id": str(case.id),
        "case_name": case.name,
        "pass": len(reasons) == 0,
        "reason": "; ".join(reasons) if reasons else None,
        "actual_preview": (actual_text or "")[:500],
        "quality_score": quality_score,
        "latency_ms": latency_ms,
    }


def _invoke_agent_local(db: Session, agent: Agent, prompt: str) -> tuple[str, Optional[float], int]:
    """Invoke the agent locally via Gemma 4 (zero cloud cost) for deterministic test runs.

    Returns (response_text, quality_score, latency_ms). Quality scoring runs best-effort
    through the local auto-scorer when available; returns None if the scorer is unreachable.
    """
    from app.services.local_inference import generate_luna_response_sync

    start = time.time()
    system_prompt = (agent.persona_prompt or agent.description or "You are a helpful agent.").strip()
    try:
        response_text = generate_luna_response_sync(
            user_message=prompt,
            system_prompt=system_prompt,
            conversation_history=[],
        ) or ""
    except Exception as exc:
        logger.warning("Local inference failed for agent %s test: %s", agent.id, exc)
        response_text = ""
    latency_ms = int((time.time() - start) * 1000)

    quality_score: Optional[float] = None
    try:
        from app.services.auto_quality_scorer import score_response_sync

        score_result = score_response_sync(prompt, response_text, tool_calls=[])
        if isinstance(score_result, dict):
            total = score_result.get("total_score")
            if isinstance(total, (int, float)):
                quality_score = float(total) / 100.0
    except Exception:
        pass

    return response_text, quality_score, latency_ms


def run_test_suite(
    db: Session,
    *,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    triggered_by_user_id: Optional[uuid.UUID] = None,
    run_type: str = "manual",
) -> AgentTestRun:
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.tenant_id == tenant_id).first()
    if not agent:
        raise ValueError("Agent not found")

    cases = (
        db.query(AgentTestCase)
        .filter(
            AgentTestCase.agent_id == agent_id,
            AgentTestCase.tenant_id == tenant_id,
            AgentTestCase.enabled.is_(True),
        )
        .all()
    )

    run = AgentTestRun(
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_version=agent.version,
        triggered_by_user_id=triggered_by_user_id,
        run_type=run_type,
        status="running",
        total_cases=len(cases),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    results = []
    passed = 0
    failed = 0
    for case in cases:
        response_text, quality, latency_ms = _invoke_agent_local(db, agent, case.input)
        entry = _score_case(response_text, quality, latency_ms, case)
        results.append(entry)
        if entry["pass"]:
            passed += 1
        else:
            failed += 1

    run.results = results
    run.passed_count = passed
    run.failed_count = failed
    run.status = "passed" if failed == 0 and len(cases) > 0 else ("error" if len(cases) == 0 else "failed")
    run.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run
