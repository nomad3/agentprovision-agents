"""Alpha Control Plane v2 API.

Versioned under /api/v2 to keep the legacy v1 envelope unchanged for
existing consumers (ChatPage.js, etc.). The cockpit and future
channel adapters subscribe here.

See docs/plans/2026-05-15-alpha-control-plane-design.md §5
"""
from fastapi import APIRouter

from . import session_events
from . import internal_session_events

router = APIRouter()
router.include_router(session_events.router, tags=["v2-session-events"])
router.include_router(internal_session_events.router, tags=["v2-internal-session-events"])
