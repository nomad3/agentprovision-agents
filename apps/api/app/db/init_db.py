import json
import time
import uuid
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from app.db import base  # noqa: F401
from app.db.session import engine

# make sure all SQL Alchemy models are imported (app.db.base) before initializing DB
# otherwise, SQL Alchemy might fail to initialize relationships properly
# for more details: https://github.com/tiangolo/full-stack-fastapi-postgresql/issues/28
from app.models.user import User
from app.models.tenant import Tenant
from app.models.data_source import DataSource
from app.models.data_pipeline import DataPipeline
from app.models.notebook import Notebook
from app.models.agent import Agent
from app.models.agent_group import AgentGroup  # noqa: F401
from app.models.agent_relationship import AgentRelationship  # noqa: F401
from app.models.agent_task import AgentTask  # noqa: F401
from app.models.agent_skill import AgentSkill  # noqa: F401
from app.models.agent_memory import AgentMemory  # noqa: F401
from app.models.knowledge_entity import KnowledgeEntity  # noqa: F401
from app.models.knowledge_relation import KnowledgeRelation  # noqa: F401
from app.models.tenant_branding import TenantBranding  # noqa: F401
from app.models.tenant_features import TenantFeatures  # noqa: F401
from app.models.tenant_analytics import TenantAnalytics  # noqa: F401
from app.models.tool import Tool
from app.models.deployment import Deployment  # noqa: F401
from app.models.vector_store import VectorStore  # noqa: F401
from app.models.agent_integration_config import AgentIntegrationConfig  # noqa: F401
from app.models.chat import ChatSession, ChatMessage
from app.models.agent_permission import AgentPermission  # noqa: F401
from app.models.integration_credential import IntegrationCredential  # noqa: F401

from app.core.security import get_password_hash
from app.services import datasets as dataset_service

def init_db(db: Session) -> None:
    # Tables should be created with Alembic migrations
    # But for this initial setup, we'll create them directly

    # Add retry logic for database connection
    max_retries = 10
    retry_delay = 5  # seconds

    for i in range(max_retries):
        try:
            print(f"Attempting to connect to database (attempt {i+1}/{max_retries})...")
            base.Base.metadata.create_all(bind=engine)
            print("Database connection successful and tables created.")
            break
        except OperationalError as e:
            print(f"Database connection failed: {e}")
            if i < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("Max retries reached. Could not connect to database.")
                raise

    seed_demo_data(db)
    seed_system_skills(db)


def seed_demo_data(db: Session) -> None:
    demo_email = "test@example.com"
    existing_user = db.query(User).filter(User.email == demo_email).first()
    if existing_user:
        return

    demo_tenant = Tenant(name="Demo Enterprise")
    db.add(demo_tenant)
    db.flush()

    demo_user = User(
        email=demo_email,
        full_name="Demo Operator",
        hashed_password=get_password_hash("password"),
        tenant_id=demo_tenant.id,
        is_active=True,
    )
    db.add(demo_user)

    data_sources = [
        DataSource(
            name="PostgreSQL Data Warehouse",
            type="warehouse",
            config={},
            tenant_id=demo_tenant.id,
        ),
        DataSource(
            name="Product Telemetry Stream",
            type="stream",
            config={},
            tenant_id=demo_tenant.id,
        ),
    ]
    for ds in data_sources:
        db.add(ds)
    db.flush()

    # Create a default Agent
    luna = Agent(
        name="Luna",
        description="General purpose AI assistant",
        tenant_id=demo_tenant.id,
        config={"llm_model": "claude-3-5-sonnet-20241022"},
        status="production",
        owner_user_id=demo_user.id
    )
    db.add(luna)
    
    db.commit()


def seed_system_skills(db: Session) -> None:
    """Seed system scoring rubrics as skills for the demo tenant."""
    from app.services.scoring_rubrics import RUBRICS

    # Find demo tenant
    demo_tenant = db.query(Tenant).filter(Tenant.name == "Demo Enterprise").first()
    if not demo_tenant:
        return

    # Check if skills table exists (migration 040 may not have run yet)
    try:
        result = db.execute(text("SELECT 1 FROM skills LIMIT 1"))
        result.close()
    except Exception:
        db.rollback()
        print("Skills table not found, skipping system skills seeding.")
        return

    for rubric_id, rubric in RUBRICS.items():
        # Check if this rubric already exists as a skill for the demo tenant
        existing = db.execute(
            text("SELECT id FROM skills WHERE tenant_id = :tid AND name = :name AND is_system = true LIMIT 1"),
            {"tid": str(demo_tenant.id), "name": rubric["name"]},
        ).first()

        if existing:
            continue

        skill_id = str(uuid.uuid4())
        db.execute(
            text(
                "INSERT INTO skills (id, tenant_id, name, description, skill_type, config, is_system, enabled, created_at, updated_at) "
                "VALUES (:id, :tid, :name, :desc, :stype, :config, true, true, now(), now())"
            ),
            {
                "id": skill_id,
                "tid": str(demo_tenant.id),
                "name": rubric["name"],
                "desc": rubric["description"],
                "stype": "scoring",
                "config": json.dumps(rubric),
            },
        )

    db.commit()
    print(f"System skills seeded: {len(RUBRICS)} rubrics checked.")
