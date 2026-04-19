from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session
import uuid

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentBase

def get_agent(db: Session, agent_id: uuid.UUID) -> Agent | None:
    return db.query(Agent).filter(Agent.id == agent_id).first()

def get_agents_by_tenant(db: Session, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Agent]:
    return db.query(Agent).filter(Agent.tenant_id == tenant_id).offset(skip).limit(limit).all()

def create_tenant_agent(db: Session, *, item_in: AgentCreate, tenant_id: uuid.UUID) -> Agent:
    db_item = Agent(**item_in.dict(), tenant_id=tenant_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def update_agent(db: Session, *, db_obj: Agent, obj_in: AgentBase) -> Agent:
    if isinstance(obj_in, dict):
        update_data = obj_in
    else:
        update_data = obj_in.dict(exclude_unset=True)

    for field in update_data:
        if hasattr(db_obj, field):
            setattr(db_obj, field, update_data[field])

    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def delete_agent(db: Session, *, agent_id: uuid.UUID) -> Agent | None:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return None

    aid = str(agent_id)

    # Nullify nullable FK references
    for tbl, col in [
        ("execution_traces", "agent_id"),
        ("chat_messages", "agent_id"),
        ("knowledge_entities", "source_agent_id"),
        ("knowledge_relations", "discovered_by_agent_id")
    ]:
        try:
            with db.begin_nested():
                db.execute(text(f"UPDATE {tbl} SET {col} = NULL WHERE {col} = :aid"), {"aid": aid})
        except Exception:
            pass

    # Delete owned records
    for tbl, col in [
        ("agent_skills", "agent_id"),
        ("deployments", "agent_id"),
        ("agent_tasks", "assigned_agent_id"),
        ("agent_tasks", "created_by_agent_id"),
        ("agent_relationships", "from_agent_id"),
        ("agent_relationships", "to_agent_id"),
        ("agent_messages", "from_agent_id"),
        ("agent_messages", "to_agent_id"),
        ("agent_memory", "agent_id"),
    ]:
        try:
            with db.begin_nested():
                db.execute(text(f"DELETE FROM {tbl} WHERE {col} = :aid"), {"aid": aid})
        except Exception:
            pass

    db.delete(agent)
    db.commit()
    return agent
