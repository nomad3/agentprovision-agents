# Review-gate MEDIUM follow-ups (Luna step-4 gaps #3 + #4)

**Date:** 2026-05-24
**Author:** Claudia (Opus 4.7)
**Reviewer:** Luna Supervisor (pending)
**Status:** design — implementation chained into 2 PRs

## Context

Yesterday's blameless RL experiment (`docs/plans/2026-05-24-blameless-rl-fine-tune-experiment.md`) surfaced 4 real gaps Luna applied to her own Code-Reviewer / Substrate-Sentinel introduction. 2 HIGH items shipped in PR #705. The 2 MEDIUM items remain:

- **Gap #3** — reviewer-unavailable should block merge. Today, if Code Reviewer / Substrate Sentinel are unreachable (LLM API down, agent disabled, dispatch error), the failure is logged but merge proceeds. Silent fail-open.
- **Gap #4** — introduction-PR review circularity fallback. A PR that modifies an agent's own `tool_groups`, persona, or skill.md frontmatter cannot reliably be reviewed by that same agent — the agent reading the diff is operating under the OLD config but the diff *defines* its new config. I hit this case with PR #705 (which changed `tool_groups` on both Code Reviewer and Substrate Sentinel) and had to manually route to Luna Supervisor instead.

Both gaps live in the same surface (`apps/api/app/services/review_service.py:start_review`) so they chain.

## Scope — YAGNI checkpoint

**In scope:**
- Detection libraries + CLI subcommands callable before merge.
- Wired into `review_service.start_review` so the formal review flow short-circuits when broken.
- Fail-closed semantics (refuse to dispatch + emit a structured reason).

**Out of scope (explicitly NOT building):**
- GitHub App / webhook layer that turns review status into a required GH check. The current review flow is operator-driven (`alpha review start`, `alpha chat send`), not webhook-driven. Adding webhooks now is infrastructure for hypothetical future use.
- Auto-fallback to a secondary reviewer that automatically *replaces* the unreachable one. The fallback in Phase 1 is operator-attestation (`alpha review override --reason ...`) — automating it later requires more trust in the alternate reviewer's quality. Today, surfacing the gap is the win.

## Phase 1 — Circularity detection (PR A)

### Surface
New module `apps/api/app/services/review_circularity.py` (~80 lines).

```python
@dataclass
class CircularityFinding:
    agent_slug: str       # the reviewer agent that owns the modified file
    bundled_path: str     # e.g. "apps/api/app/agents/_bundled/code-reviewer/skill.md"
    escalation_slug: str | None  # supervisor to route to instead (via escalation_agent_id)

def detect_self_modification(
    db: Session,
    tenant_id: UUID,
    changed_files: list[str],
    candidate_reviewer_slugs: list[str],
) -> tuple[list[str], list[CircularityFinding]]:
    """Return (filtered_reviewers, findings).

    For each candidate reviewer, check whether the PR modifies the
    agent's own bundled skill.md or any file under its
    apps/api/app/agents/_bundled/<slug>/ directory. If yes, remove the
    reviewer from the candidate list and record a finding with the
    escalation_agent_id-resolved supervisor slug.
    """
```

### Call site
`review_service.start_review` before `ReviewCoalition.clis` is populated (around `apps/api/app/services/review_service.py:413`):

```python
filtered_slugs, circularity_findings = detect_self_modification(
    db, tenant_id, changed_files, [c["agent_slug"] for c in cli_list]
)
cli_list = [c for c in cli_list if c["agent_slug"] in filtered_slugs]
# circularity_findings → blackboard DECISION entry + return value
```

### CLI surface
`alpha review check-circularity --pr <num>` — prints findings + non-zero exit if any reviewer is circular. Lets operator/Luna inspect before dispatch.

### Test plan
- Unit: feed a fake `changed_files` list including `apps/api/app/agents/_bundled/code-reviewer/skill.md`, assert `code-reviewer` is filtered out + the finding lists Luna as escalation.
- Unit: feed a list with no bundled-agent paths, assert no filtering.
- Unit: bundled path under a slug not present in `candidate_reviewer_slugs` → no-op (we don't filter agents we weren't going to dispatch anyway).

## Phase 2 — Availability check (PR B, chained off PR A)

### Surface
New module `apps/api/app/services/reviewer_availability.py` (~60 lines).

```python
@dataclass
class UnavailabilityReason:
    agent_slug: str
    reason: Literal["agent_missing", "agent_disabled", "no_dispatch_in_window", "review_required_unresolved"]
    detail: str

def check_required_reviewers(
    db: Session,
    tenant_id: UUID,
    required_slugs: list[str],
    *,
    stale_dispatch_minutes: int = 60,
) -> list[UnavailabilityReason]:
    """Return unavailable reviewers. Empty list = all reachable.

    Checks per agent:
      1. Agent exists in this tenant (else agent_missing).
      2. Agent.status != "deprecated" and not in draft (else agent_disabled).
      3. Agent does NOT have tool_groups_review_required=TRUE (else
         review_required_unresolved — reviewer is itself awaiting
         operator review and shouldn't be acting as a gate).
      4. Last successful dispatch within stale_dispatch_minutes (else
         no_dispatch_in_window).
    """
```

Check #3 is the bridge to PR #705's `tool_groups_review_required` flag — a reviewer that's itself in the review queue can't be a trusted gate.

### Call site
Same location in `review_service.start_review`, immediately after circularity filtering:

```python
unavailable = check_required_reviewers(db, tenant_id, [c["agent_slug"] for c in cli_list])
if unavailable:
    raise ReviewerUnavailableError(reasons=unavailable)
```

`ReviewerUnavailableError` is caught by the API layer (`apps/api/app/api/v1/reviews.py`) and returns 409 Conflict + the structured reasons. Operator sees the gap explicitly; no silent fail-open.

### Operator override
`alpha review override --pr <num> --reason "<message>"` writes the attestation to the blackboard + emits an audit log entry. Lets work continue when the operator has out-of-band knowledge that the reviewer is fine.

### CLI surface
`alpha review check-availability --slugs code-reviewer,substrate-sentinel` — prints unavailable reviewers + non-zero exit. Same pattern as PR A's CLI.

### Test plan
- Unit: agent that's missing → `agent_missing`.
- Unit: agent with `tool_groups_review_required=TRUE` → `review_required_unresolved`.
- Unit: agent with no dispatch in last 60 min → `no_dispatch_in_window`.
- Unit: all healthy → empty list.
- Integration: `start_review` with all reviewers unavailable raises `ReviewerUnavailableError` (caught at API layer).

## Walk-through — applying this to PR #705 retrospectively

**Changed files (relevant subset):** `apps/api/app/agents/_bundled/code-reviewer/skill.md`, `apps/api/app/agents/_bundled/substrate-sentinel/skill.md`.

**Phase 1 output:**
```
filtered_reviewers = ["luna-supervisor"]   # code-reviewer + substrate-sentinel removed
findings = [
  {agent_slug: "code-reviewer", bundled_path: "..._bundled/code-reviewer/skill.md", escalation_slug: "luna-supervisor"},
  {agent_slug: "substrate-sentinel", bundled_path: "..._bundled/substrate-sentinel/skill.md", escalation_slug: "luna-supervisor"},
]
```

**Phase 2 output:** Luna-supervisor is reachable → empty list → dispatch proceeds with Luna only.

Outcome matches what I did manually today. The two PRs convert that manual judgment call into a deterministic gate.

## Why two PRs not one

- Per `feedback_single_pr_for_feature`: each PR is one self-contained behavior with its own tests + walkthrough.
- Per `feedback_chain_pr_branches`: both touch `review_service.start_review` so PR B branches off PR A to avoid merge-cascade conflicts on the same call-site.
- Phase 1 (circularity) is cheaper to ship + gives us PR #705-class learning immediately. Phase 2 (availability) needs the dispatch-success-tracking column which doesn't exist yet and adds a migration.

## Open questions for Luna's review

1. Should the circularity gate be strict (any file under `_bundled/<slug>/` blocks) or only `skill.md` frontmatter changes? PR A goes strict by default; Luna's call if too aggressive.
2. For Phase 2's "no dispatch in window" check — what's the right staleness threshold? 60 min is a guess; tenant-configurable later.
3. Phase 2's `review_required_unresolved` check creates a chicken-and-egg: Code Reviewer + Substrate Sentinel both shipped with `review_required=TRUE` from migration 153, so until an operator clears them they can never act as reviewers. Intentional or do we need a "trusted-on-introduction" exemption?

## Out-of-band fallback already in place

For the case where these gates fire and there is no automated path forward, operator (Simon) or Luna can always dispatch directly via `alpha chat send --agent <uuid>`. The gates introduce friction, not a hard wall.
