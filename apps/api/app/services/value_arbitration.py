"""Value Arbitration — pure-function library.

Per ``docs/plans/2026-05-23-value-arbitration-design.md`` (Claudia +
Luna co-design, dialogue session ``05979efd-a06a-4956-9df9-3fd84ec3c10d``).

**SCOPE: PURE LIBRARY ONLY — NO RUNTIME WIRING.**

Per §0 Hard Gate of the design doc: the arbitrator + dataclasses +
fixtures + tests ship now, but ABSOLUTELY NO live decision path may
import or call this module until P0a (tool-permission gate) and P0c
(audit fail-loud) land + verify in production. Importing this module
into ``agent_router.py`` / ``cli_session_manager.py`` / any decision
surface is a scope violation per the plan.

Design rationale (compressed):
  - 9 value-source classes (``SourceClass``) — ``safety_floor``,
    ``substrate_integrity``, ``tenant_norm``, ``operator_intent``,
    ``user_of_moment``, ``peer_agent``, ``agent_value_set``,
    ``self_affective_history``, ``future_self``.
  - 4 standing classes (``Standing``) — ``absolute`` (hierarchical
    override), ``veto_bearing`` (disjunctive veto), ``strong_advisory``,
    ``advisory``.
  - 4 directions (``Direction``) — ``pursue`` / ``avoid`` / ``veto`` /
    ``preserve``.
  - 4 outcomes (``ArbitrationOutcome``) — ``preferred`` / ``blocked`` /
    ``abstain`` / ``throttled``. ``throttled`` is the dedicated outcome
    for ``substrate_integrity`` vetoes (operational deferral, NOT moral
    refusal — see §9 resolved-by-Luna note).

Veto rule corrections from Luna review 2026-05-23 (binding):
  - Absolute veto = hierarchical override. Any single absolute veto
    blocks regardless of any lower-standing signal.
  - Veto-bearing = DISJUNCTIVE (any single veto blocks). Earlier draft
    required unanimity; that was fail-open. Defense against rogue
    veto-bearing sources lives at the registration boundary, NOT at
    consensus on blocking.
  - ``substrate_integrity`` vetoes produce ``ArbitrationOutcome.throttled``,
    not ``blocked``. Throttled = "valid action, substrate cannot run it
    now" (retriable; does NOT train the value layer as moral refusal).

Provenance contract (§4.2): every ``ValueSignal`` MUST carry
``{source, source_id, timestamp, tenant_id, confidence}`` and
``agent_id`` unless ``source`` is ``safety_floor`` or ``tenant_norm``.
``validate_signal()`` raises ``MissingProvenance`` for any breach;
the exception is NOT swallowed.

Purity contract (matches ``agent_value_set.py``):
  - No DB calls.
  - No logging beyond module-level stdlib.
  - No hidden state. Every input is in the function signature.
  - Audit/persistence belongs in a future IO wrapper, not here.
"""
from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

log = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────


class SourceClass(str, enum.Enum):
    """Nine value-source classes per design §4.1.

    ``safety_floor`` and ``substrate_integrity`` are platform-level.
    ``tenant_norm`` is operator-declared per tenant.
    ``operator_intent`` / ``user_of_moment`` / ``peer_agent`` are
    request-scoped. ``agent_value_set`` / ``self_affective_history`` /
    ``future_self`` are agent-scoped.
    """

    safety_floor = "safety_floor"
    substrate_integrity = "substrate_integrity"
    tenant_norm = "tenant_norm"
    operator_intent = "operator_intent"
    user_of_moment = "user_of_moment"
    peer_agent = "peer_agent"
    agent_value_set = "agent_value_set"
    self_affective_history = "self_affective_history"
    future_self = "future_self"


class Standing(str, enum.Enum):
    """Four standing classes per design §4.1.

    ``absolute`` is hierarchical (any single absolute veto wins
    regardless of any lower-standing signal). ``veto_bearing`` is
    disjunctive within class (any single veto blocks). Advisories
    enter the weighted sum.
    """

    absolute = "absolute"
    veto_bearing = "veto_bearing"
    strong_advisory = "strong_advisory"
    advisory = "advisory"


class Direction(str, enum.Enum):
    """Four signal directions per design §4.2."""

    pursue = "pursue"
    avoid = "avoid"
    veto = "veto"
    preserve = "preserve"


class ArbitrationOutcome(str, enum.Enum):
    """Four arbitration outcomes per design §4.3 + §9 resolution.

    ``throttled`` is distinct from ``blocked`` so substrate-integrity
    vetoes do NOT train the value layer as moral refusal — operational
    deferral is retriable and surfaces differently in operator UX.
    """

    preferred = "preferred"
    blocked = "blocked"
    abstain = "abstain"
    throttled = "throttled"


# ── Exceptions ────────────────────────────────────────────────────────


class MissingProvenance(ValueError):
    """Raised when a ``ValueSignal`` lacks required provenance fields.

    Per design §4.2 boundary rule: this exception MUST propagate to
    the caller. Swallowing it reproduces the failure mode the whole
    arbitration layer exists to prevent.
    """


# ── Sources that allow ``agent_id`` to be null ────────────────────────

# Per design §4.2: every signal carries an ``agent_id`` EXCEPT
# safety_floor + tenant_norm (those are platform/tenant-scoped, not
# agent-scoped).
_AGENT_OPTIONAL_SOURCES = frozenset(
    {SourceClass.safety_floor, SourceClass.tenant_norm}
)


# ── Standing-class weight bounds ──────────────────────────────────────


_STANDING_BOUNDS: dict[Standing, Tuple[float, float]] = {
    Standing.absolute: (1.0, 1.0),
    Standing.veto_bearing: (1.0, 1.0),
    Standing.strong_advisory: (0.5, 2.0),
    Standing.advisory: (0.1, 1.0),
}


def standing_bounds(standing: Standing) -> Tuple[float, float]:
    """Return ``(min, max)`` weight clamp for a standing class."""
    return _STANDING_BOUNDS[standing]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Default tie epsilon ───────────────────────────────────────────────

# §9 open question 4: actual value to be tuned against the test corpus
# before production wiring. 0.05 is the spec's working default.
TIE_EPSILON: float = 0.05


# ── Dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValueTarget:
    """Identifier for the candidate-action a signal applies to.

    ``kind`` is the action category (``tool_call``, ``response``,
    ``workflow_step``, ``memory_write``, ``coalition_election``).
    ``ref`` is the action-specific identifier (tool name, candidate ID,
    step name). Matching against a ``Candidate`` is done by
    ``match_signal_to_candidate`` — exact ``(kind, ref)`` match returns
    1.0, ``kind``-only match returns 0.5, else 0.0.
    """

    kind: str
    ref: str


@dataclass(frozen=True)
class ValueSignal:
    """A single value-input under arbitration.

    All provenance fields are REQUIRED per design §4.2. ``agent_id``
    may be ``None`` only when ``source`` is ``safety_floor`` or
    ``tenant_norm``. ``confidence`` is a [0.0, 1.0] float; ``None`` is
    rejected at the boundary.
    """

    # Provenance — REQUIRED
    source: SourceClass
    source_id: str
    timestamp: datetime
    tenant_id: uuid.UUID
    agent_id: Optional[uuid.UUID]
    confidence: Optional[float]
    # Payload
    standing: Standing
    direction: Direction
    target: ValueTarget
    rationale: str = ""
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """An action the arbitration is choosing among / evaluating.

    For binary allow/deny decisions, pass a single ``Candidate`` and
    interpret ``ArbitrationResult.outcome`` (``preferred`` = allow,
    ``blocked`` / ``throttled`` = deny).
    """

    kind: str
    ref: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionContext:
    """The arbitration call's context — agent, session, tenant, action."""

    tenant_id: uuid.UUID
    agent_id: Optional[uuid.UUID]
    session_id: Optional[uuid.UUID] = None
    action_kind: str = ""
    action_ref: str = ""


@dataclass
class TrustWeights:
    """Per-(tenant, source_class, agent) trust weight store.

    Pure read-side data carrier. Reads return the most specific entry
    available — exact ``(tenant_id, source_class, agent_id)``, then
    ``(tenant_id, source_class, None)``, then default 1.0. Writes /
    reflection-driven updates live in the future IO wrapper.
    """

    # key = (tenant_id, source_class, agent_id_or_None)
    weights: dict = field(default_factory=dict)
    default: float = 1.0

    def get(
        self,
        tenant_id: uuid.UUID,
        source_class: SourceClass,
        agent_id: Optional[uuid.UUID],
    ) -> float:
        if (tenant_id, source_class, agent_id) in self.weights:
            return float(self.weights[(tenant_id, source_class, agent_id)])
        if (tenant_id, source_class, None) in self.weights:
            return float(self.weights[(tenant_id, source_class, None)])
        return float(self.default)


@dataclass(frozen=True)
class TraceEntry:
    """One row in the arbitration trace.

    Captures the signal's provenance + the rule applied + the resulting
    contribution (or ``rejected`` reason). Audit consumers replay
    arbitrations from these entries + the weights snapshot.
    """

    source: SourceClass
    source_id: str
    standing: Standing
    direction: Direction
    target_kind: str
    target_ref: str
    confidence: float
    weight_raw: float
    weight_clamped: float
    contribution_per_candidate: dict  # candidate_ref -> float
    rule: str  # 'absolute_veto' | 'substrate_throttle' | 'veto_bearing_block' | 'weighted' | 'rejected'
    rejected_reason: Optional[str] = None


@dataclass(frozen=True)
class ArbitrationResult:
    """Output of ``arbitrate()``.

    ``outcome`` is one of preferred / blocked / abstain / throttled.
    For ``preferred``, ``ordering`` is the candidates ranked best-first
    and ``scores`` maps candidate-ref → weighted-sum score. For
    blocked / throttled / abstain, ``reason`` carries the rule that
    fired. ``trace`` is the per-signal record (admitted AND rejected).
    """

    outcome: ArbitrationOutcome
    ordering: tuple = ()
    scores: dict = field(default_factory=dict)
    reason: Optional[str] = None
    trace: tuple = ()
    rejected: tuple = ()

    @classmethod
    def preferred(
        cls,
        ordering,
        scores: dict,
        trace: tuple,
        rejected: tuple = (),
    ) -> "ArbitrationResult":
        return cls(
            outcome=ArbitrationOutcome.preferred,
            ordering=tuple(ordering),
            scores=dict(scores),
            trace=tuple(trace),
            rejected=tuple(rejected),
        )

    @classmethod
    def blocked(
        cls,
        reason: str,
        trace: tuple,
        rejected: tuple = (),
    ) -> "ArbitrationResult":
        return cls(
            outcome=ArbitrationOutcome.blocked,
            reason=reason,
            trace=tuple(trace),
            rejected=tuple(rejected),
        )

    @classmethod
    def throttled(
        cls,
        reason: str,
        trace: tuple,
        rejected: tuple = (),
    ) -> "ArbitrationResult":
        return cls(
            outcome=ArbitrationOutcome.throttled,
            reason=reason,
            trace=tuple(trace),
            rejected=tuple(rejected),
        )

    @classmethod
    def abstain(
        cls,
        reason: str,
        trace: tuple,
        rejected: tuple = (),
        scores: Optional[dict] = None,
        ordering=(),
    ) -> "ArbitrationResult":
        return cls(
            outcome=ArbitrationOutcome.abstain,
            reason=reason,
            trace=tuple(trace),
            rejected=tuple(rejected),
            scores=dict(scores or {}),
            ordering=tuple(ordering),
        )


# ── Boundary validation ───────────────────────────────────────────────


def validate_signal(sig: ValueSignal) -> bool:
    """Validate provenance per §4.2 boundary rule.

    Returns ``True`` if the signal is admissible. Raises
    ``MissingProvenance`` otherwise — the caller MUST NOT swallow.
    """
    missing: list[str] = []
    if sig.source is None:
        missing.append("source")
    if not sig.source_id:
        missing.append("source_id")
    if sig.timestamp is None:
        missing.append("timestamp")
    if sig.tenant_id is None:
        missing.append("tenant_id")
    if sig.confidence is None:
        missing.append("confidence")
    # agent_id required for every source except safety_floor + tenant_norm
    if sig.agent_id is None and sig.source not in _AGENT_OPTIONAL_SOURCES:
        missing.append("agent_id")
    if missing:
        raise MissingProvenance(
            f"ValueSignal missing provenance fields: {missing} "
            f"(source={sig.source!r}, source_id={sig.source_id!r})"
        )
    # confidence must be a number in [0, 1]
    if not (0.0 <= float(sig.confidence) <= 1.0):
        raise MissingProvenance(
            f"ValueSignal confidence out of [0,1]: {sig.confidence}"
        )
    return True


# ── Signal-to-candidate matcher ───────────────────────────────────────


def match_signal_to_candidate(sig: ValueSignal, cand: Candidate) -> float:
    """Return applicability of ``sig`` to ``cand`` in ``[0, 1]``.

    1.0 = exact ``(kind, ref)`` match.
    0.5 = ``kind`` match only (signal applies to the action category
          but not this specific candidate).
    0.0 = no match (signal contributes nothing to this candidate's
          score).
    """
    if sig.target.kind == cand.kind and sig.target.ref == cand.ref:
        return 1.0
    if sig.target.kind == cand.kind:
        return 0.5
    return 0.0


# ── Core arbitration ──────────────────────────────────────────────────


def _sign_for_direction(d: Direction) -> int:
    if d == Direction.pursue:
        return +1
    if d in (Direction.avoid, Direction.veto):
        return -1
    # preserve / unknown → no contribution to weighted sum
    return 0


def arbitrate(
    context: DecisionContext,
    signals: list,
    trust_weights: TrustWeights,
    candidates: list,
    tie_epsilon: float = TIE_EPSILON,
) -> ArbitrationResult:
    """Pure arbitration over plural value signals.

    Steps (per design §4.3, with Luna review corrections folded in):

      1. Validate every signal at the boundary. Provenance-rejected
         signals enter the trace as ``rejected`` with reason; they do
         NOT contribute to scoring.
      2. ABSOLUTE pass — any single absolute veto blocks (hierarchical
         override; no lower-standing signal can rescue).
      3. SUBSTRATE-INTEGRITY pass — any single substrate_integrity
         veto produces ``throttled``, NOT ``blocked``. Throttled is
         operational deferral, distinct from moral refusal (§9
         Luna-resolved). Runs BEFORE other veto-bearing so substrate
         vetoes don't get mis-classified as moral.
      4. VETO-BEARING pass (excluding substrate_integrity) — any
         single veto from a veto-bearing source blocks. DISJUNCTIVE
         per Luna review correction; earlier unanimity draft was
         fail-open.
      5. WEIGHTED SUM — every admitted signal contributes
         ``sign * applicability * weight * confidence`` to each
         candidate. ``weight`` is clamped to the standing class's
         bounds at read time.
      6. TIE-BREAK — top two candidates within ``tie_epsilon`` →
         abstain. Surface indeterminacy; do NOT coin-flip.

    Audit + persistence belong in the IO wrapper. This function is
    pure and side-effect-free.
    """
    # Step 1: boundary validation. We catch MissingProvenance here to
    # build a rejected-signal trace; the rest of the system upstream of
    # arbitrate() is what is forbidden from swallowing the exception
    # silently (per §4.2). Including rejected signals in the trace is
    # explicit per §4.3 final bullet.
    valid: list = []
    rejected_entries: list = []
    for sig in signals:
        try:
            validate_signal(sig)
            valid.append(sig)
        except MissingProvenance as exc:
            rejected_entries.append(
                TraceEntry(
                    source=sig.source if sig.source is not None else SourceClass.peer_agent,
                    source_id=str(sig.source_id or ""),
                    standing=sig.standing if sig.standing is not None else Standing.advisory,
                    direction=sig.direction if sig.direction is not None else Direction.preserve,
                    target_kind=sig.target.kind if sig.target is not None else "",
                    target_ref=sig.target.ref if sig.target is not None else "",
                    confidence=float(sig.confidence) if sig.confidence is not None else 0.0,
                    weight_raw=0.0,
                    weight_clamped=0.0,
                    contribution_per_candidate={},
                    rule="rejected",
                    rejected_reason=str(exc),
                )
            )

    trace: list = list(rejected_entries)

    # Step 2: absolute pass — hierarchical override.
    absolute_signals = [s for s in valid if s.standing == Standing.absolute]
    absolute_vetoes = [s for s in absolute_signals if s.direction == Direction.veto]
    if absolute_vetoes:
        for s in absolute_vetoes:
            trace.append(_trace_for_veto(s, rule="absolute_veto"))
        # Carry the remaining admitted signals into trace too, marked as
        # bypassed-by-absolute, so audit replay is complete.
        for s in valid:
            if s in absolute_vetoes:
                continue
            trace.append(_trace_for_bypass(s, rule="bypassed_by_absolute"))
        return ArbitrationResult.blocked(
            reason="absolute_veto",
            trace=tuple(trace),
            rejected=tuple(rejected_entries),
        )

    # Step 3: substrate-integrity pass — DISTINCT throttled outcome.
    substrate_vetoes = [
        s
        for s in valid
        if s.source == SourceClass.substrate_integrity and s.direction == Direction.veto
    ]
    if substrate_vetoes:
        for s in substrate_vetoes:
            trace.append(_trace_for_veto(s, rule="substrate_throttle"))
        for s in valid:
            if s in substrate_vetoes:
                continue
            trace.append(_trace_for_bypass(s, rule="bypassed_by_substrate"))
        return ArbitrationResult.throttled(
            reason="substrate_integrity_throttle",
            trace=tuple(trace),
            rejected=tuple(rejected_entries),
        )

    # Step 4: veto-bearing pass — DISJUNCTIVE (Luna correction).
    # Excludes substrate_integrity (handled above with throttle outcome).
    veto_class = [
        s
        for s in valid
        if s.standing == Standing.veto_bearing
        and s.source != SourceClass.substrate_integrity
    ]
    vetoes = [s for s in veto_class if s.direction == Direction.veto]
    if vetoes:
        for s in vetoes:
            trace.append(_trace_for_veto(s, rule="veto_bearing_block"))
        for s in valid:
            if s in vetoes:
                continue
            trace.append(_trace_for_bypass(s, rule="bypassed_by_veto_bearing"))
        return ArbitrationResult.blocked(
            reason="veto_bearing_block",
            trace=tuple(trace),
            rejected=tuple(rejected_entries),
        )

    # Step 5: weighted sum.
    scores: dict = {(c.kind, c.ref): 0.0 for c in candidates}
    for sig in valid:
        raw = trust_weights.get(
            tenant_id=context.tenant_id,
            source_class=sig.source,
            agent_id=context.agent_id,
        )
        lo, hi = standing_bounds(sig.standing)
        clamped = _clamp(raw, lo, hi)
        sign = _sign_for_direction(sig.direction)
        contributions: dict = {}
        for cand in candidates:
            applicability = match_signal_to_candidate(sig, cand)
            contrib = sign * applicability * clamped * float(sig.confidence)
            scores[(cand.kind, cand.ref)] += contrib
            contributions[cand.ref] = contrib
        trace.append(
            TraceEntry(
                source=sig.source,
                source_id=sig.source_id,
                standing=sig.standing,
                direction=sig.direction,
                target_kind=sig.target.kind,
                target_ref=sig.target.ref,
                confidence=float(sig.confidence),
                weight_raw=raw,
                weight_clamped=clamped,
                contribution_per_candidate=contributions,
                rule="weighted",
            )
        )

    # Step 6: tie-break.
    ordering = sorted(
        candidates, key=lambda c: -scores[(c.kind, c.ref)]
    )
    scores_by_ref = {f"{c.kind}:{c.ref}": scores[(c.kind, c.ref)] for c in candidates}

    if len(ordering) >= 2:
        top = scores[(ordering[0].kind, ordering[0].ref)]
        runner = scores[(ordering[1].kind, ordering[1].ref)]
        if abs(top - runner) < tie_epsilon:
            return ArbitrationResult.abstain(
                reason="tie_within_epsilon",
                trace=tuple(trace),
                rejected=tuple(rejected_entries),
                scores=scores_by_ref,
                ordering=tuple(ordering),
            )

    return ArbitrationResult.preferred(
        ordering=tuple(ordering),
        scores=scores_by_ref,
        trace=tuple(trace),
        rejected=tuple(rejected_entries),
    )


# ── Trace helpers ─────────────────────────────────────────────────────


def _trace_for_veto(sig: ValueSignal, rule: str) -> TraceEntry:
    return TraceEntry(
        source=sig.source,
        source_id=sig.source_id,
        standing=sig.standing,
        direction=sig.direction,
        target_kind=sig.target.kind,
        target_ref=sig.target.ref,
        confidence=float(sig.confidence),
        weight_raw=1.0,
        weight_clamped=1.0,
        contribution_per_candidate={},
        rule=rule,
    )


def _trace_for_bypass(sig: ValueSignal, rule: str) -> TraceEntry:
    return TraceEntry(
        source=sig.source,
        source_id=sig.source_id,
        standing=sig.standing,
        direction=sig.direction,
        target_kind=sig.target.kind,
        target_ref=sig.target.ref,
        confidence=float(sig.confidence),
        weight_raw=0.0,
        weight_clamped=0.0,
        contribution_per_candidate={},
        rule=rule,
    )
