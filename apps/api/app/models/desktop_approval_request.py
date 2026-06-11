"""Luna P5.4b — agent-facing pending desktop approval requests.

One row per "Luna asked to run a native desktop action and is waiting for a human
to approve it" (the pending-approval branch of the agent act surface). This is a
REQUEST, not a grant: it lives in its own table and is invisible to the command
claim path (which only consumes ``DesktopCommandApprovalGrant.status == 'active'``),
so a pending request can NEVER authorize a native action. The P5.5 user-approval
surface is what flips ``pending -> approved`` and mints the real grant
(``grant_id`` then points at it).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class DesktopApprovalRequest(Base):
    __tablename__ = "desktop_approval_requests"
    __table_args__ = (
        Index(
            "idx_desktop_approval_requests_tenant_status",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "idx_desktop_approval_requests_session",
            "session_id",
        ),
    )

    # Single-column lookups are covered by the composite indexes in
    # __table_args__ (tenant_id+status, session_id) + the PK (id-scoped poll), so
    # no per-column index=True flags here — keeps the model in lockstep with the
    # migration 176 DDL (which creates only the two composite indexes).
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The principal the request is attributed to (the chat session owner). Used
    # for scope checks; NOT an approver — approval is a separate human action.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    shell_id = Column(String(96), nullable=False)
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_registry.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Native-control action class only (pointer_*/keyboard_*) — the actions that
    # need a user grant. Plain String, no DDL enum (matches the rest of the
    # desktop-control tables).
    action = Column(String(48), nullable=False)
    capability = Column(String(64), nullable=False)
    # Reduced, display-safe target descriptor ({"bundle_id": ...}). Never a raw
    # payload bag, screenshot, OCR text, or window title.
    target_binding = Column(JSONB, nullable=False, default=dict)
    # Optional agent-supplied rationale, length-capped + display-safe.
    reason = Column(Text, nullable=True)
    # pending (default) -> approved | denied | expired | cancelled.
    status = Column(String(32), nullable=False, default="pending")
    requested_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Set only by the P5.5 approval surface when it mints the real grant. A
    # pending request has no grant; this is how "request -> grant" is recorded.
    grant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("desktop_command_approval_grants.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
