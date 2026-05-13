"""TrainingRun — one initial-training pass per tenant per wedge channel.

Lifecycle: pending → running → (complete | failed). See
`docs/plans/2026-05-11-ap-quickstart-design.md` §7 for the broader flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


# Allowed `status` values. Kept here (not as a Postgres ENUM) so we can
# add states without a migration when the workflow grows new lifecycle
# stages — e.g. "paused" or "needs_review" in a future PR.
TRAINING_RUN_STATUSES = frozenset({"pending", "running", "complete", "failed"})

# Allowed `source` values. Mirrors the wedge channels enumerated in the
# quickstart design doc §3. The web/CLI clients pass one of these in the
# POST body; the endpoint validates against this set so an unknown
# source can't poison the workflow with no extraction adapter.
TRAINING_RUN_SOURCES = frozenset(
    {"local_ai_cli", "github_cli", "gmail", "calendar", "slack", "whatsapp"}
)


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source = Column(String(32), nullable=False)
    # Client-supplied idempotency key. `(tenant_id, snapshot_id)` has a
    # unique index — re-POSTing the same snapshot returns the existing
    # row without spawning a parallel workflow. This is what lets
    # `alpha quickstart --resume` retry safely.
    snapshot_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    items_total = Column(Integer, nullable=False, default=0)
    items_processed = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    # Temporal workflow id — `TrainingIngestionWorkflow-<run_id>`. Stored
    # for forensic queries even though Temporal also indexes by it; the
    # SQL row is the user-visible audit anchor.
    workflow_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # No relationship() back to Tenant — keeps the model lightweight and
    # avoids a forced eager-load cycle. Caller joins explicitly.

    def progress_fraction(self) -> Optional[float]:
        """Convenience for UI progress bars. None when total is unknown
        (workflow hasn't reported a count yet)."""
        if not self.items_total:
            return None
        return min(1.0, self.items_processed / self.items_total)
