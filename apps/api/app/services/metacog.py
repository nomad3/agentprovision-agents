"""Metacognition pure-function layer (M1 of #616).

Serialize/deserialize for the agent_memory substrate + ECE
calibration helper. Pure functions only — no DB session, no logging.
The IO layer (metacog_io.py) wraps these with persistence concerns.

Mirrors the team_engine.py pattern (#608): pure logic here so the
IO layer's tests can hit DB while these tests stay fast.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from app.schemas.metacog import (
    ConfidencePrediction,
    MetacogTrace,
    OutcomeObservation,
)

logger = logging.getLogger(__name__)


# ── Memory type discriminators ────────────────────────────────────────
PREDICTION_MEMORY_TYPE = "metacog_confidence_prediction"
OBSERVATION_MEMORY_TYPE = "metacog_outcome_observation"


# ── Serialize / deserialize ───────────────────────────────────────────


def serialize_prediction(prediction: ConfidencePrediction) -> str:
    """JSON-encode a ConfidencePrediction for agent_memory.content."""
    return json.dumps(prediction.to_dict(), sort_keys=True)


def deserialize_prediction(blob: str) -> Optional[ConfidencePrediction]:
    """Best-effort decode. Returns None on malformed content rather
    than raising — the caller (read path) skips and logs."""
    try:
        data = json.loads(blob)
        return ConfidencePrediction(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug(
            "metacog.deserialize_prediction: malformed blob — %s", exc
        )
        return None


def serialize_observation(observation: OutcomeObservation) -> str:
    """JSON-encode an OutcomeObservation for agent_memory.content."""
    return json.dumps(observation.to_dict(), sort_keys=True)


def deserialize_observation(blob: str) -> Optional[OutcomeObservation]:
    try:
        data = json.loads(blob)
        return OutcomeObservation(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug(
            "metacog.deserialize_observation: malformed blob — %s", exc
        )
        return None


# ── ECE / calibration ─────────────────────────────────────────────────


def expected_calibration_error(
    traces: Iterable[MetacogTrace],
    bins: int = 10,
) -> float:
    """Expected Calibration Error (Naeini et al., 2015).

    Lower is better; 0.0 = perfectly calibrated. The classic metric:
    bin predictions into `bins` equal-width buckets in [0, 1], for
    each non-empty bucket compute |mean_predicted − mean_actual|, then
    weight by bucket size and sum.

    Luna's call (#616 §9): start with 10 bins. Operator can pass
    `bins=20` for high-volume decision kinds if calibration drifts
    show low-resolution artefacts.

    Returns NaN-safe 0.0 when input is empty. Trace inputs that fail
    the (prediction.decision_id == observation.decision_id) invariant
    are MetacogTrace construction errors and don't reach here.
    """
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    materialized = list(traces)
    n_total = len(materialized)
    if n_total == 0:
        return 0.0

    bin_width = 1.0 / bins
    buckets: list[list[MetacogTrace]] = [[] for _ in range(bins)]
    for t in materialized:
        pred = t.prediction.predicted_confidence
        # Edge case: prediction of exactly 1.0 lands in the last bucket,
        # not in an out-of-range index. The 0.999… clamp protects against
        # floating-point cases where 1.0 / bin_width would yield `bins`.
        idx = min(int(pred / bin_width), bins - 1)
        buckets[idx].append(t)

    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        mean_pred = sum(b.prediction.predicted_confidence for b in bucket) / len(bucket)
        mean_actual = sum(b.normalized_reward for b in bucket) / len(bucket)
        ece += (len(bucket) / n_total) * abs(mean_pred - mean_actual)
    return ece


# ── Join helper ───────────────────────────────────────────────────────


def join_traces(
    predictions: Iterable[ConfidencePrediction],
    observations: Iterable[OutcomeObservation],
) -> list[MetacogTrace]:
    """Pair predictions with their matching observations by
    decision_id. Returns MetacogTrace list; unpaired predictions or
    observations are silently dropped (an observation without its
    prediction can't be calibrated; a prediction without its
    observation is just in-flight).

    Stable: input order is preserved for predictions; the resulting
    list contains a trace for each prediction that has a matching
    observation, in prediction order.
    """
    obs_by_id = {o.decision_id: o for o in observations}
    out: list[MetacogTrace] = []
    for p in predictions:
        o = obs_by_id.get(p.decision_id)
        if o is None:
            continue
        try:
            out.append(MetacogTrace(prediction=p, observation=o))
        except ValueError as exc:
            # Tenant-mismatch or other invariant breach — log and skip.
            logger.warning(
                "metacog.join_traces: skipping malformed trace "
                "decision_id=%s err=%s",
                p.decision_id, exc,
            )
    return out


__all__ = [
    "PREDICTION_MEMORY_TYPE",
    "OBSERVATION_MEMORY_TYPE",
    "serialize_prediction",
    "deserialize_prediction",
    "serialize_observation",
    "deserialize_observation",
    "expected_calibration_error",
    "join_traces",
]
