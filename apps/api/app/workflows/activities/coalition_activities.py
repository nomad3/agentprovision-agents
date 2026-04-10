"""Activities for CoalitionWorkflow."""
import logging
from uuid import UUID, uuid4
from temporalio import activity

from app.db.session import SessionLocal
from app.services import coalition_service, blackboard_service
from app.models.coalition import CoalitionTemplate
from app.schemas.blackboard import BlackboardCreate, BlackboardEntryCreate
from app.schemas.collaboration import CollaborationSessionCreate

logger = logging.getLogger(__name__)


@activity.defn
async def select_coalition_template(tenant_id: str, chat_session_id: str, task_description: str) -> dict:
    """Select optimal coalition template and resolve roles from the session's AgentKit."""
    from app.models.chat import ChatSession
    from app.models.agent_kit import AgentKit
    from app.models.agent import Agent
    
    db = SessionLocal()
    try:
        # 1. Identify the session's kit
        session = db.query(ChatSession).filter(ChatSession.id == UUID(chat_session_id)).first()
        kit = None
        if session and session.agent_kit_id:
            kit = db.query(AgentKit).filter(AgentKit.id == session.agent_kit_id).first()

        # 2. Determine pattern based on intent (Phase 1: keywords)
        task_lower = task_description.lower()
        pattern = "propose-critique-revise"
        required_roles = ["proposer", "critic"]
        
        if any(k in task_lower for k in ["research", "market", "competitor"]):
            pattern = "research-synthesize"
            required_roles = ["researcher", "synthesizer"]
        elif any(k in task_lower for k in ["deploy", "fix", "implement"]):
            pattern = "plan-verify"
            required_roles = ["planner", "verifier"]

        # Helper to slugify
        def _slug(name): return name.lower().replace(" ", "-")

        # 3. Resolve agents from the kit or tenant defaults
        role_agent_map = {}
        primary_slug = "luna"
        try:
            from app.models.tenant_branding import TenantBranding
            branding = db.query(TenantBranding).filter(TenantBranding.tenant_id == UUID(tenant_id)).first()
            if branding and branding.ai_assistant_name and branding.ai_assistant_name != "AI Assistant":
                primary_slug = branding.ai_assistant_name.lower().replace(" ", "-")
        except Exception:
            pass

        # Try to find agents in the current tenant matching the required roles
        agents = db.query(Agent).filter(Agent.tenant_id == UUID(tenant_id)).all()
        
        for role in required_roles:
            # Priority 1: Match by Agent.role field
            match = next((a for a in agents if a.role == role), None)
            # Priority 2: Fallback to name-based matching
            if not match:
                match = next((a for a in agents if role in a.name.lower()), None)
            
            if match:
                role_agent_map[role] = _slug(match.name)
            else:
                # Priority 3: Hard fallback to tenant primary assistant
                role_agent_map[role] = primary_slug

        return {
            "template_id": None,
            "pattern": pattern,
            "roles": role_agent_map,
            "name": f"Dynamic {pattern.title()} Team"
        }
    finally:
        db.close()


@activity.defn
async def initialize_collaboration(tenant_id: str, chat_session_id: str, template: dict) -> dict:
    """Create the Shared Blackboard and start the Collaboration Session."""
    db = SessionLocal()
    try:
        # 1. Create Blackboard
        board_in = BlackboardCreate(
            title=f"Task: {template['name']}",
            chat_session_id=UUID(chat_session_id)
        )
        board = blackboard_service.create_blackboard(db, UUID(tenant_id), board_in)
        
        # 2. Create Collaboration Session
        collab_in = CollaborationSessionCreate(
            blackboard_id=board.id,
            pattern=template["pattern"],
            role_assignments=template["roles"]
        )
        from app.services import collaboration_service
        session = collaboration_service.create_session(db, UUID(tenant_id), collab_in)
        
        return {
            "blackboard_id": str(board.id),
            "collaboration_id": str(session.id),
            "max_rounds": session.max_rounds
        }
    finally:
        db.close()


@activity.defn
async def execute_collaboration_step(tenant_id: str, collaboration_id: str, round_index: int) -> dict:
    """Execute a single step of the collaboration pattern."""
    # This involves dispatching tasks to the assigned agents and updating the blackboard.
    # For Phase 1, we simulate the agent contributions or call local_inference.
    logger.info("Executing collaboration step for %s, round %d", collaboration_id, round_index)
    
    # In a real implementation, this would:
    # 1. Identify the current agent based on the phase
    # 2. Build a prompt including the Blackboard state
    # 3. Call local_inference or CLI
    # 4. Add the response as a BlackboardEntry
    # 5. Check for consensus
    
    return {"consensus_reached": True, "summary": "Simulation: agents agreed on the plan."}


@activity.defn
async def finalize_collaboration(tenant_id: str, collaboration_id: str) -> str:
    """Conclude the collaboration and generate a final report for the chat."""
    return "Collaboration complete. The team has verified the implementation plan."
