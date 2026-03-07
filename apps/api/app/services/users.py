from typing import List

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services import tenants as tenant_service
from app.schemas.tenant import TenantCreate
from app.models.agent_kit import AgentKit
import uuid

def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_email(db: Session, *, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()

def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[User]:
    return db.query(User).offset(skip).limit(limit).all()

def create_user(db: Session, *, user_in: UserCreate, tenant_id: uuid.UUID) -> User:
    db_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        tenant_id=tenant_id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def create_user_with_tenant(db: Session, *, user_in: UserCreate, tenant_in: TenantCreate) -> User:
    tenant = tenant_service.create_tenant(db, tenant_in=tenant_in)
    default_kit = AgentKit(
        name="Luna Supervisor",
        description="Luna is your AI co-pilot. She coordinates specialized teams for data analysis, sales, marketing, development, and more.",
        version="1.0.0",
        kit_type="hierarchy",
        industry=None,
        config={
            "model": "claude-3-5-sonnet-20240620",
            "personality": "friendly",
            "temperature": 0.7,
            "max_tokens": 2000,
            "tools": ["entity_extraction", "knowledge_search", "lead_scoring", "calculator", "data_summary"],
            "system_prompt": "You are Luna, an intelligent AI co-pilot. Route requests to the best specialized team and provide helpful, actionable responses.",
        },
        default_hierarchy={
            "supervisor": "servicetsunami_supervisor",
            "workers": ["personal_assistant", "dev_team", "data_team", "sales_team", "marketing_team"],
        },
        tenant_id=tenant.id,
    )
    db.add(default_kit)
    db_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        tenant_id=tenant.id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user



def update_user(db: Session, *, db_user: User, user_in: UserUpdate) -> User:
    if user_in.full_name is not None:
        db_user.full_name = user_in.full_name
    if user_in.email is not None:
        db_user.email = user_in.email
    if user_in.password is not None:
        db_user.hashed_password = get_password_hash(user_in.password)
    if user_in.is_active is not None:
        db_user.is_active = user_in.is_active
    if user_in.is_superuser is not None:
        db_user.is_superuser = user_in.is_superuser
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user(db: Session, *, user_id: uuid.UUID) -> User | None:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return user