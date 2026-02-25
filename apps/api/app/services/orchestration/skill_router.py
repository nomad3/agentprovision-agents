"""
Skill Router Service - Stub after OpenClaw removal.

OpenClaw integration has been removed. This module retains the SkillRouter
class signature so that existing imports don't break, but all methods return
'not available' until a replacement skill execution backend is wired in.
"""

import uuid
import logging
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SkillRouter:
    """Stub skill router — OpenClaw backend has been removed."""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    def execute_skill(
        self,
        skill_name: str,
        payload: Dict[str, Any],
        task_id: Optional[uuid.UUID] = None,
        agent_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        return {"status": "error", "error": "Skill execution backend not available (OpenClaw removed)"}

    def health_check(self) -> Dict[str, Any]:
        return {"status": "not_available", "healthy": False}

    def call_gateway_method(
        self,
        method: str,
        params: Dict[str, Any] = None,
        timeout_seconds: int = 30,
    ) -> Dict[str, Any]:
        return {"status": "error", "error": "Gateway not available (OpenClaw removed)"}
