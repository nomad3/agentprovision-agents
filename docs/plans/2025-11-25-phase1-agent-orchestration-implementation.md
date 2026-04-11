# Phase 1: Agent Orchestration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add multi-agent orchestration with agent groups, hierarchies, task delegation, and inter-agent communication.

**Architecture:** Extend existing Agent model, add AgentGroup/AgentRelationship/AgentTask/AgentMessage/AgentSkill models. Create OrchestrationService for task delegation. Add API routes and integrate with existing chat flow.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pydantic, pytest

**Reference:** See `docs/plans/2025-11-25-enterprise-ai-platform-design.md` for full design details.

---

## Task 1: Extend Agent Model with Orchestration Fields

**Files:**
- Modify: `apps/api/app/models/agent.py`
- Modify: `apps/api/app/schemas/agent.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Create file `apps/api/tests/test_agent_orchestration.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import uuid
import os

os.environ["TESTING"] = "True"

from app.main import app
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.api.deps import get_db
from app.models.agent import Agent

def override_get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="auth_token")
def auth_token_fixture(db_session):
    """Create user and get auth token."""
    client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {"email": "orchestration@test.com", "password": "testpass123", "full_name": "Test"},
            "tenant_in": {"name": "Orchestration Tenant"}
        }
    )
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "orchestration@test.com", "password": "testpass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    return response.json()["access_token"]


def test_agent_has_orchestration_fields(db_session):
    """Test that Agent model has new orchestration fields."""
    agent = Agent(
        name="Test Agent",
        description="Test",
        config={},
        tenant_id=uuid.uuid4(),
        role="analyst",
        capabilities=["sql_query", "summarization"],
        personality={"tone": "professional"},
        autonomy_level="supervised",
        max_delegation_depth=2
    )
    db_session.add(agent)
    db_session.commit()

    assert agent.role == "analyst"
    assert agent.capabilities == ["sql_query", "summarization"]
    assert agent.personality == {"tone": "professional"}
    assert agent.autonomy_level == "supervised"
    assert agent.max_delegation_depth == 2


def test_create_agent_with_orchestration_fields(db_session, auth_token):
    """Test creating agent via API with new fields."""
    response = client.post(
        "/api/v1/agents",
        json={
            "name": "Research Agent",
            "description": "Researches topics",
            "config": {"model": "claude"},
            "role": "researcher",
            "capabilities": ["web_search", "summarization"],
            "personality": {"tone": "academic", "verbosity": "detailed"},
            "autonomy_level": "supervised",
            "max_delegation_depth": 1
        },
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "researcher"
    assert data["capabilities"] == ["web_search", "summarization"]
    assert data["autonomy_level"] == "supervised"
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_has_orchestration_fields -v
```

Expected: FAIL with `TypeError: __init__() got unexpected keyword argument 'role'`

**Step 3: Update Agent model**

Modify `apps/api/app/models/agent.py`:

```python
import uuid
from sqlalchemy import Column, String, ForeignKey, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    config = Column(JSON)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    tenant = relationship("Tenant")

    # Orchestration fields (NEW)
    role = Column(String, nullable=True)  # "analyst", "manager", "specialist"
    capabilities = Column(JSON, nullable=True)  # ["sql_query", "summarization"]
    personality = Column(JSON, nullable=True)  # {"tone": "professional", "verbosity": "concise"}
    autonomy_level = Column(String, default="supervised")  # "full", "supervised", "approval_required"
    max_delegation_depth = Column(Integer, default=2)

    # Future: llm_config_id, memory_config (added in later phases)
```

**Step 4: Update Agent schema**

Modify `apps/api/app/schemas/agent.py`:

```python
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uuid


class AgentBase(BaseModel):
    name: str
    description: Optional[str] = None
    config: dict
    # Orchestration fields
    role: Optional[str] = None
    capabilities: Optional[List[str]] = None
    personality: Optional[Dict[str, Any]] = None
    autonomy_level: Optional[str] = "supervised"
    max_delegation_depth: Optional[int] = 2


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    role: Optional[str] = None
    capabilities: Optional[List[str]] = None
    personality: Optional[Dict[str, Any]] = None
    autonomy_level: Optional[str] = None
    max_delegation_depth: Optional[int] = None


class Agent(AgentBase):
    id: uuid.UUID
    tenant_id: uuid.UUID

    class Config:
        from_attributes = True
```

**Step 5: Run tests to verify they pass**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/models/agent.py apps/api/app/schemas/agent.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(agent): add orchestration fields (role, capabilities, personality, autonomy)"
```

---

## Task 2: Create AgentGroup Model

**Files:**
- Create: `apps/api/app/models/agent_group.py`
- Create: `apps/api/app/schemas/agent_group.py`
- Modify: `apps/api/app/db/init_db.py` (import new model)
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to `apps/api/tests/test_agent_orchestration.py`:

```python
from app.models.agent_group import AgentGroup


def test_agent_group_model(db_session):
    """Test AgentGroup model creation."""
    group = AgentGroup(
        name="Sales Team",
        description="Handles sales inquiries",
        tenant_id=uuid.uuid4(),
        goal="Close enterprise deals",
        strategy={"approach": "consultative"},
        shared_context={"industry": "tech"},
        escalation_rules={"timeout_minutes": 30}
    )
    db_session.add(group)
    db_session.commit()

    assert group.id is not None
    assert group.name == "Sales Team"
    assert group.goal == "Close enterprise deals"
    assert group.strategy == {"approach": "consultative"}
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_group_model -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.agent_group'`

**Step 3: Create AgentGroup model**

Create file `apps/api/app/models/agent_group.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentGroup(Base):
    """Agent team/group for multi-agent orchestration."""
    __tablename__ = "agent_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Team configuration
    goal = Column(String, nullable=True)  # Team objective
    strategy = Column(JSON, nullable=True)  # How team approaches problems
    shared_context = Column(JSON, nullable=True)  # Knowledge all agents share
    escalation_rules = Column(JSON, nullable=True)  # When to escalate to supervisor

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant")
```

**Step 4: Create AgentGroup schema**

Create file `apps/api/app/schemas/agent_group.py`:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


class AgentGroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    goal: Optional[str] = None
    strategy: Optional[Dict[str, Any]] = None
    shared_context: Optional[Dict[str, Any]] = None
    escalation_rules: Optional[Dict[str, Any]] = None


class AgentGroupCreate(AgentGroupBase):
    pass


class AgentGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    strategy: Optional[Dict[str, Any]] = None
    shared_context: Optional[Dict[str, Any]] = None
    escalation_rules: Optional[Dict[str, Any]] = None


class AgentGroup(AgentGroupBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentGroupWithMembers(AgentGroup):
    """AgentGroup with member agents included."""
    members: List[dict] = []  # Will include agent details
```

**Step 5: Update init_db.py to import new model**

Modify `apps/api/app/db/init_db.py` - add import at top:

```python
from app.models.agent_group import AgentGroup  # noqa: F401
```

**Step 6: Run tests to verify they pass**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_group_model -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add apps/api/app/models/agent_group.py apps/api/app/schemas/agent_group.py apps/api/app/db/init_db.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentGroup model for multi-agent teams"
```

---

## Task 3: Create AgentRelationship Model

**Files:**
- Create: `apps/api/app/models/agent_relationship.py`
- Create: `apps/api/app/schemas/agent_relationship.py`
- Modify: `apps/api/app/db/init_db.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to `apps/api/tests/test_agent_orchestration.py`:

```python
from app.models.agent_relationship import AgentRelationship


def test_agent_relationship_model(db_session):
    """Test AgentRelationship for defining agent hierarchy."""
    tenant_id = uuid.uuid4()

    # Create group
    group = AgentGroup(name="Test Group", tenant_id=tenant_id)
    db_session.add(group)
    db_session.flush()

    # Create agents
    manager = Agent(name="Manager", config={}, tenant_id=tenant_id, role="manager")
    worker = Agent(name="Worker", config={}, tenant_id=tenant_id, role="analyst")
    db_session.add_all([manager, worker])
    db_session.flush()

    # Create relationship
    rel = AgentRelationship(
        group_id=group.id,
        from_agent_id=manager.id,
        to_agent_id=worker.id,
        relationship_type="supervises",
        trust_level=0.9,
        communication_style="sync",
        handoff_rules={"auto_delegate": True}
    )
    db_session.add(rel)
    db_session.commit()

    assert rel.id is not None
    assert rel.relationship_type == "supervises"
    assert rel.trust_level == 0.9
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_relationship_model -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create AgentRelationship model**

Create file `apps/api/app/models/agent_relationship.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentRelationship(Base):
    """Defines relationships between agents within a group."""
    __tablename__ = "agent_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("agent_groups.id"), nullable=False)
    from_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    to_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)

    # Relationship configuration
    relationship_type = Column(String, nullable=False)  # "supervises", "delegates_to", "collaborates_with", "reports_to", "consults"
    trust_level = Column(Float, default=0.5)  # 0-1, affects autonomy
    communication_style = Column(String, default="async")  # "sync", "async", "broadcast"
    handoff_rules = Column(JSON, nullable=True)  # When/how to pass work

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    group = relationship("AgentGroup")
    from_agent = relationship("Agent", foreign_keys=[from_agent_id])
    to_agent = relationship("Agent", foreign_keys=[to_agent_id])
```

**Step 4: Create AgentRelationship schema**

Create file `apps/api/app/schemas/agent_relationship.py`:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import uuid


class AgentRelationshipBase(BaseModel):
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    relationship_type: str  # "supervises", "delegates_to", "collaborates_with", "reports_to", "consults"
    trust_level: Optional[float] = 0.5
    communication_style: Optional[str] = "async"
    handoff_rules: Optional[Dict[str, Any]] = None


class AgentRelationshipCreate(AgentRelationshipBase):
    group_id: uuid.UUID


class AgentRelationshipUpdate(BaseModel):
    relationship_type: Optional[str] = None
    trust_level: Optional[float] = None
    communication_style: Optional[str] = None
    handoff_rules: Optional[Dict[str, Any]] = None


class AgentRelationship(AgentRelationshipBase):
    id: uuid.UUID
    group_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True
```

**Step 5: Update init_db.py**

Add import to `apps/api/app/db/init_db.py`:

```python
from app.models.agent_relationship import AgentRelationship  # noqa: F401
```

**Step 6: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_relationship_model -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add apps/api/app/models/agent_relationship.py apps/api/app/schemas/agent_relationship.py apps/api/app/db/init_db.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentRelationship model for agent hierarchy"
```

---

## Task 4: Create AgentTask Model

**Files:**
- Create: `apps/api/app/models/agent_task.py`
- Create: `apps/api/app/schemas/agent_task.py`
- Modify: `apps/api/app/db/init_db.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to `apps/api/tests/test_agent_orchestration.py`:

```python
from app.models.agent_task import AgentTask


def test_agent_task_model(db_session):
    """Test AgentTask for tracking work units."""
    tenant_id = uuid.uuid4()

    group = AgentGroup(name="Task Group", tenant_id=tenant_id)
    db_session.add(group)
    db_session.flush()

    agent = Agent(name="Worker", config={}, tenant_id=tenant_id)
    db_session.add(agent)
    db_session.flush()

    task = AgentTask(
        group_id=group.id,
        assigned_agent_id=agent.id,
        human_requested=True,
        status="queued",
        priority="high",
        task_type="analyze",
        objective="Analyze Q4 sales data",
        context={"dataset_id": "123"},
        requires_approval=False
    )
    db_session.add(task)
    db_session.commit()

    assert task.id is not None
    assert task.status == "queued"
    assert task.priority == "high"
    assert task.objective == "Analyze Q4 sales data"
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_task_model -v
```

Expected: FAIL

**Step 3: Create AgentTask model**

Create file `apps/api/app/models/agent_task.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Float, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from decimal import Decimal

from app.db.base import Base


class AgentTask(Base):
    """Work unit assigned to an agent."""
    __tablename__ = "agent_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("agent_groups.id"), nullable=True)
    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    created_by_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)

    # Task origin
    human_requested = Column(Boolean, default=True)

    # Status tracking
    status = Column(String, default="queued")  # queued, thinking, executing, waiting_input, delegated, reviewing, completed, failed
    priority = Column(String, default="normal")  # critical, high, normal, low, background

    # Task definition
    task_type = Column(String, nullable=True)  # research, analyze, generate, decide, execute
    objective = Column(String, nullable=False)
    context = Column(JSON, nullable=True)  # Input data, conversation history

    # Execution details
    reasoning = Column(JSON, nullable=True)  # Chain of thought
    output = Column(JSON, nullable=True)  # Results
    confidence = Column(Float, nullable=True)  # Agent's confidence in result 0-1
    error = Column(String, nullable=True)  # Error message if failed

    # Subtask hierarchy
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)

    # Approval workflow
    requires_approval = Column(Boolean, default=False)
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Cost tracking
    tokens_used = Column(Integer, default=0)
    cost = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    group = relationship("AgentGroup")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    created_by_agent = relationship("Agent", foreign_keys=[created_by_agent_id])
    parent_task = relationship("AgentTask", remote_side=[id])
```

**Step 4: Create AgentTask schema**

Create file `apps/api/app/schemas/agent_task.py`:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


class AgentTaskBase(BaseModel):
    objective: str
    task_type: Optional[str] = None
    priority: Optional[str] = "normal"
    context: Optional[Dict[str, Any]] = None
    requires_approval: Optional[bool] = False


class AgentTaskCreate(AgentTaskBase):
    assigned_agent_id: uuid.UUID
    group_id: Optional[uuid.UUID] = None
    parent_task_id: Optional[uuid.UUID] = None


class AgentTaskUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    reasoning: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    error: Optional[str] = None


class AgentTask(AgentTaskBase):
    id: uuid.UUID
    group_id: Optional[uuid.UUID]
    assigned_agent_id: uuid.UUID
    created_by_agent_id: Optional[uuid.UUID]
    human_requested: bool
    status: str
    reasoning: Optional[Dict[str, Any]]
    output: Optional[Dict[str, Any]]
    confidence: Optional[float]
    error: Optional[str]
    parent_task_id: Optional[uuid.UUID]
    tokens_used: int
    cost: float
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class AgentTaskWithSubtasks(AgentTask):
    """Task with subtasks included."""
    subtasks: List["AgentTask"] = []
```

**Step 5: Update init_db.py**

Add import:

```python
from app.models.agent_task import AgentTask  # noqa: F401
```

**Step 6: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_task_model -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add apps/api/app/models/agent_task.py apps/api/app/schemas/agent_task.py apps/api/app/db/init_db.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentTask model for work tracking"
```

---

## Task 5: Create AgentMessage Model

**Files:**
- Create: `apps/api/app/models/agent_message.py`
- Create: `apps/api/app/schemas/agent_message.py`
- Modify: `apps/api/app/db/init_db.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to `apps/api/tests/test_agent_orchestration.py`:

```python
from app.models.agent_message import AgentMessage


def test_agent_message_model(db_session):
    """Test AgentMessage for inter-agent communication."""
    tenant_id = uuid.uuid4()

    group = AgentGroup(name="Message Group", tenant_id=tenant_id)
    db_session.add(group)
    db_session.flush()

    sender = Agent(name="Sender", config={}, tenant_id=tenant_id)
    receiver = Agent(name="Receiver", config={}, tenant_id=tenant_id)
    db_session.add_all([sender, receiver])
    db_session.flush()

    msg = AgentMessage(
        group_id=group.id,
        from_agent_id=sender.id,
        to_agent_id=receiver.id,
        message_type="request",
        content={"action": "analyze", "data": {"file": "sales.csv"}},
        reasoning="Need detailed analysis for quarterly report",
        requires_response=True
    )
    db_session.add(msg)
    db_session.commit()

    assert msg.id is not None
    assert msg.message_type == "request"
    assert msg.requires_response is True
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_message_model -v
```

**Step 3: Create AgentMessage model**

Create file `apps/api/app/models/agent_message.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentMessage(Base):
    """Inter-agent communication message."""
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("agent_groups.id"), nullable=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)
    from_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    to_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)  # Null = broadcast

    # Message content
    message_type = Column(String, nullable=False)  # request, response, handoff, escalation, update, question, approval_request
    content = Column(JSON, nullable=False)  # The actual message
    reasoning = Column(String, nullable=True)  # Why sending this message

    # Response handling
    requires_response = Column(Boolean, default=False)
    response_deadline = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    group = relationship("AgentGroup")
    task = relationship("AgentTask")
    from_agent = relationship("Agent", foreign_keys=[from_agent_id])
    to_agent = relationship("Agent", foreign_keys=[to_agent_id])
```

**Step 4: Create AgentMessage schema**

Create file `apps/api/app/schemas/agent_message.py`:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import uuid


class AgentMessageBase(BaseModel):
    message_type: str  # request, response, handoff, escalation, update, question, approval_request
    content: Dict[str, Any]
    reasoning: Optional[str] = None
    requires_response: Optional[bool] = False
    response_deadline: Optional[datetime] = None


class AgentMessageCreate(AgentMessageBase):
    from_agent_id: uuid.UUID
    to_agent_id: Optional[uuid.UUID] = None  # Null = broadcast
    group_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None


class AgentMessage(AgentMessageBase):
    id: uuid.UUID
    group_id: Optional[uuid.UUID]
    task_id: Optional[uuid.UUID]
    from_agent_id: uuid.UUID
    to_agent_id: Optional[uuid.UUID]
    created_at: datetime

    class Config:
        from_attributes = True
```

**Step 5: Update init_db.py**

```python
from app.models.agent_message import AgentMessage  # noqa: F401
```

**Step 6: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_message_model -v
```

**Step 7: Commit**

```bash
git add apps/api/app/models/agent_message.py apps/api/app/schemas/agent_message.py apps/api/app/db/init_db.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentMessage model for inter-agent communication"
```

---

## Task 6: Create AgentSkill Model

**Files:**
- Create: `apps/api/app/models/agent_skill.py`
- Create: `apps/api/app/schemas/agent_skill.py`
- Modify: `apps/api/app/db/init_db.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to test file:

```python
from app.models.agent_skill import AgentSkill


def test_agent_skill_model(db_session):
    """Test AgentSkill for learnable capabilities."""
    tenant_id = uuid.uuid4()

    agent = Agent(name="Skilled Agent", config={}, tenant_id=tenant_id)
    db_session.add(agent)
    db_session.flush()

    skill = AgentSkill(
        agent_id=agent.id,
        skill_name="sql_query",
        proficiency=0.8,
        times_used=150,
        success_rate=0.95,
        learned_from="training",
        examples=[{"input": "show sales", "output": "SELECT * FROM sales"}]
    )
    db_session.add(skill)
    db_session.commit()

    assert skill.id is not None
    assert skill.skill_name == "sql_query"
    assert skill.proficiency == 0.8
    assert skill.success_rate == 0.95
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_skill_model -v
```

**Step 3: Create AgentSkill model**

Create file `apps/api/app/models/agent_skill.py`:

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentSkill(Base):
    """Learnable skill/capability for an agent."""
    __tablename__ = "agent_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)

    # Skill definition
    skill_name = Column(String, nullable=False)  # "sql_query", "summarization", "negotiation"
    proficiency = Column(Float, default=0.5)  # 0-1, improves with use

    # Usage metrics
    times_used = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)

    # Learning source
    learned_from = Column(String, nullable=True)  # "training", "observation", "practice", "feedback"
    examples = Column(JSON, nullable=True)  # Good examples for few-shot learning

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="skills")
```

**Step 4: Update Agent model to add skills relationship**

Add to `apps/api/app/models/agent.py`:

```python
# Add to Agent class:
skills = relationship("AgentSkill", back_populates="agent")
```

**Step 5: Create AgentSkill schema**

Create file `apps/api/app/schemas/agent_skill.py`:

```python
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
import uuid


class AgentSkillBase(BaseModel):
    skill_name: str
    proficiency: Optional[float] = 0.5
    learned_from: Optional[str] = None
    examples: Optional[List[Any]] = None


class AgentSkillCreate(AgentSkillBase):
    agent_id: uuid.UUID


class AgentSkillUpdate(BaseModel):
    proficiency: Optional[float] = None
    examples: Optional[List[Any]] = None


class AgentSkill(AgentSkillBase):
    id: uuid.UUID
    agent_id: uuid.UUID
    times_used: int
    success_rate: float
    created_at: datetime
    last_used_at: Optional[datetime]

    class Config:
        from_attributes = True
```

**Step 6: Update init_db.py**

```python
from app.models.agent_skill import AgentSkill  # noqa: F401
```

**Step 7: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_agent_skill_model -v
```

**Step 8: Commit**

```bash
git add apps/api/app/models/agent_skill.py apps/api/app/schemas/agent_skill.py apps/api/app/models/agent.py apps/api/app/db/init_db.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentSkill model for learnable capabilities"
```

---

## Task 7: Create Agent Groups API Routes

**Files:**
- Create: `apps/api/app/services/agent_groups.py`
- Create: `apps/api/app/api/v1/agent_groups.py`
- Modify: `apps/api/app/api/v1/routes.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

Add to test file:

```python
def test_create_agent_group_api(db_session, auth_token):
    """Test creating agent group via API."""
    response = client.post(
        "/api/v1/agent_groups",
        json={
            "name": "Sales Team",
            "description": "Handles enterprise sales",
            "goal": "Close deals efficiently",
            "strategy": {"approach": "consultative"},
            "escalation_rules": {"timeout": 30}
        },
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Sales Team"
    assert data["goal"] == "Close deals efficiently"


def test_list_agent_groups_api(db_session, auth_token):
    """Test listing agent groups."""
    # Create a group first
    client.post(
        "/api/v1/agent_groups",
        json={"name": "Test Group", "goal": "Testing"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    response = client.get(
        "/api/v1/agent_groups",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    assert len(response.json()) >= 1
```

**Step 2: Run test to verify it fails**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_create_agent_group_api -v
```

Expected: FAIL with 404 (route not found)

**Step 3: Create agent_groups service**

Create file `apps/api/app/services/agent_groups.py`:

```python
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from app.models.agent_group import AgentGroup
from app.schemas.agent_group import AgentGroupCreate, AgentGroupUpdate


def create_agent_group(db: Session, group_in: AgentGroupCreate, tenant_id: uuid.UUID) -> AgentGroup:
    """Create a new agent group."""
    group = AgentGroup(
        name=group_in.name,
        description=group_in.description,
        tenant_id=tenant_id,
        goal=group_in.goal,
        strategy=group_in.strategy,
        shared_context=group_in.shared_context,
        escalation_rules=group_in.escalation_rules
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def get_agent_group(db: Session, group_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[AgentGroup]:
    """Get agent group by ID."""
    return db.query(AgentGroup).filter(
        AgentGroup.id == group_id,
        AgentGroup.tenant_id == tenant_id
    ).first()


def get_agent_groups(db: Session, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[AgentGroup]:
    """List all agent groups for a tenant."""
    return db.query(AgentGroup).filter(
        AgentGroup.tenant_id == tenant_id
    ).offset(skip).limit(limit).all()


def update_agent_group(db: Session, group_id: uuid.UUID, tenant_id: uuid.UUID, group_in: AgentGroupUpdate) -> Optional[AgentGroup]:
    """Update an agent group."""
    group = get_agent_group(db, group_id, tenant_id)
    if not group:
        return None

    update_data = group_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)

    db.commit()
    db.refresh(group)
    return group


def delete_agent_group(db: Session, group_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """Delete an agent group."""
    group = get_agent_group(db, group_id, tenant_id)
    if not group:
        return False
    db.delete(group)
    db.commit()
    return True
```

**Step 4: Create agent_groups routes**

Create file `apps/api/app/api/v1/agent_groups.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.agent_group import AgentGroup, AgentGroupCreate, AgentGroupUpdate
from app.services import agent_groups as service

router = APIRouter()


@router.post("", response_model=AgentGroup, status_code=201)
def create_agent_group(
    group_in: AgentGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new agent group."""
    return service.create_agent_group(db, group_in, current_user.tenant_id)


@router.get("", response_model=List[AgentGroup])
def list_agent_groups(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all agent groups."""
    return service.get_agent_groups(db, current_user.tenant_id, skip, limit)


@router.get("/{group_id}", response_model=AgentGroup)
def get_agent_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get agent group by ID."""
    group = service.get_agent_group(db, group_id, current_user.tenant_id)
    if not group:
        raise HTTPException(status_code=404, detail="Agent group not found")
    return group


@router.put("/{group_id}", response_model=AgentGroup)
def update_agent_group(
    group_id: uuid.UUID,
    group_in: AgentGroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an agent group."""
    group = service.update_agent_group(db, group_id, current_user.tenant_id, group_in)
    if not group:
        raise HTTPException(status_code=404, detail="Agent group not found")
    return group


@router.delete("/{group_id}", status_code=204)
def delete_agent_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an agent group."""
    if not service.delete_agent_group(db, group_id, current_user.tenant_id):
        raise HTTPException(status_code=404, detail="Agent group not found")
```

**Step 5: Register routes**

Modify `apps/api/app/api/v1/routes.py`:

```python
from fastapi import APIRouter
from app.api.v1 import (
    auth,
    data_sources,
    data_pipelines,
    notebooks,
    agents,
    tools,
    connectors,
    deployments,
    analytics,
    vector_stores,
    agent_kits,
    datasets,
    chat,
    postgres,
    internal,
    agent_groups,  # NEW
)

router = APIRouter()

# ... existing routes ...

router.include_router(agent_groups.router, prefix="/agent_groups", tags=["agent_groups"])  # NEW
```

**Step 6: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_create_agent_group_api tests/test_agent_orchestration.py::test_list_agent_groups_api -v
```

**Step 7: Commit**

```bash
git add apps/api/app/services/agent_groups.py apps/api/app/api/v1/agent_groups.py apps/api/app/api/v1/routes.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentGroups API routes"
```

---

## Task 8: Create Agent Tasks API Routes

**Files:**
- Create: `apps/api/app/services/agent_tasks.py`
- Create: `apps/api/app/api/v1/agent_tasks.py`
- Modify: `apps/api/app/api/v1/routes.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

```python
def test_create_agent_task_api(db_session, auth_token):
    """Test creating a task via API."""
    # Create an agent first
    agent_resp = client.post(
        "/api/v1/agents",
        json={"name": "Task Agent", "config": {}},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    agent_id = agent_resp.json()["id"]

    response = client.post(
        "/api/v1/tasks",
        json={
            "assigned_agent_id": agent_id,
            "objective": "Analyze quarterly data",
            "task_type": "analyze",
            "priority": "high",
            "context": {"dataset": "q4_sales"}
        },
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["objective"] == "Analyze quarterly data"
    assert data["status"] == "queued"
```

**Step 2: Create agent_tasks service**

Create file `apps/api/app/services/agent_tasks.py`:

```python
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid

from app.models.agent_task import AgentTask
from app.models.agent import Agent
from app.schemas.agent_task import AgentTaskCreate, AgentTaskUpdate


def create_task(db: Session, task_in: AgentTaskCreate, tenant_id: uuid.UUID) -> AgentTask:
    """Create a new task."""
    # Verify agent belongs to tenant
    agent = db.query(Agent).filter(
        Agent.id == task_in.assigned_agent_id,
        Agent.tenant_id == tenant_id
    ).first()
    if not agent:
        raise ValueError("Agent not found or doesn't belong to tenant")

    task = AgentTask(
        group_id=task_in.group_id,
        assigned_agent_id=task_in.assigned_agent_id,
        parent_task_id=task_in.parent_task_id,
        human_requested=True,
        status="queued",
        priority=task_in.priority or "normal",
        task_type=task_in.task_type,
        objective=task_in.objective,
        context=task_in.context,
        requires_approval=task_in.requires_approval or False
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[AgentTask]:
    """Get task by ID."""
    return db.query(AgentTask).join(Agent).filter(
        AgentTask.id == task_id,
        Agent.tenant_id == tenant_id
    ).first()


def get_tasks(db: Session, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100, status: str = None) -> List[AgentTask]:
    """List tasks for tenant."""
    query = db.query(AgentTask).join(Agent).filter(Agent.tenant_id == tenant_id)
    if status:
        query = query.filter(AgentTask.status == status)
    return query.order_by(AgentTask.created_at.desc()).offset(skip).limit(limit).all()


def update_task(db: Session, task_id: uuid.UUID, tenant_id: uuid.UUID, task_in: AgentTaskUpdate) -> Optional[AgentTask]:
    """Update a task."""
    task = get_task(db, task_id, tenant_id)
    if not task:
        return None

    update_data = task_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # Auto-set timestamps
    if task_in.status == "executing" and not task.started_at:
        task.started_at = datetime.utcnow()
    if task_in.status in ("completed", "failed"):
        task.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return task
```

**Step 3: Create agent_tasks routes**

Create file `apps/api/app/api/v1/agent_tasks.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.agent_task import AgentTask, AgentTaskCreate, AgentTaskUpdate
from app.services import agent_tasks as service

router = APIRouter()


@router.post("", response_model=AgentTask, status_code=201)
def create_task(
    task_in: AgentTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new task for an agent."""
    try:
        return service.create_task(db, task_in, current_user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=List[AgentTask])
def list_tasks(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all tasks."""
    return service.get_tasks(db, current_user.tenant_id, skip, limit, status)


@router.get("/{task_id}", response_model=AgentTask)
def get_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get task by ID."""
    task = service.get_task(db, task_id, current_user.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=AgentTask)
def update_task(
    task_id: uuid.UUID,
    task_in: AgentTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a task."""
    task = service.update_task(db, task_id, current_user.tenant_id, task_in)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
```

**Step 4: Update routes.py**

```python
from app.api.v1 import agent_tasks  # NEW

router.include_router(agent_tasks.router, prefix="/tasks", tags=["tasks"])  # NEW
```

**Step 5: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_create_agent_task_api -v
```

**Step 6: Commit**

```bash
git add apps/api/app/services/agent_tasks.py apps/api/app/api/v1/agent_tasks.py apps/api/app/api/v1/routes.py apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add AgentTasks API routes"
```

---

## Task 9: Create OrchestrationService

**Files:**
- Create: `apps/api/app/services/orchestration/__init__.py`
- Create: `apps/api/app/services/orchestration/task_dispatcher.py`
- Test: `apps/api/tests/test_agent_orchestration.py`

**Step 1: Write the failing test**

```python
from app.services.orchestration.task_dispatcher import TaskDispatcher


def test_task_dispatcher_assigns_to_best_agent(db_session):
    """Test that TaskDispatcher assigns tasks to appropriate agent."""
    tenant_id = uuid.uuid4()

    # Create group
    group = AgentGroup(name="Analysis Team", tenant_id=tenant_id)
    db_session.add(group)
    db_session.flush()

    # Create agents with different capabilities
    analyst = Agent(
        name="Data Analyst",
        config={},
        tenant_id=tenant_id,
        role="analyst",
        capabilities=["sql_query", "data_analysis"]
    )
    writer = Agent(
        name="Content Writer",
        config={},
        tenant_id=tenant_id,
        role="writer",
        capabilities=["summarization", "writing"]
    )
    db_session.add_all([analyst, writer])
    db_session.flush()

    # Create relationships
    rel1 = AgentRelationship(group_id=group.id, from_agent_id=analyst.id, to_agent_id=writer.id, relationship_type="collaborates_with")
    db_session.add(rel1)
    db_session.commit()

    dispatcher = TaskDispatcher(db_session)

    # Task requiring data_analysis should go to analyst
    best_agent = dispatcher.find_best_agent(
        group_id=group.id,
        required_capabilities=["data_analysis"],
        tenant_id=tenant_id
    )

    assert best_agent is not None
    assert best_agent.id == analyst.id
```

**Step 2: Create orchestration service**

Create directory and files:

`apps/api/app/services/orchestration/__init__.py`:
```python
from .task_dispatcher import TaskDispatcher

__all__ = ["TaskDispatcher"]
```

`apps/api/app/services/orchestration/task_dispatcher.py`:
```python
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from app.models.agent import Agent
from app.models.agent_group import AgentGroup
from app.models.agent_relationship import AgentRelationship
from app.models.agent_task import AgentTask
from app.models.agent_skill import AgentSkill


class TaskDispatcher:
    """Dispatches tasks to appropriate agents based on capabilities."""

    def __init__(self, db: Session):
        self.db = db

    def find_best_agent(
        self,
        group_id: uuid.UUID,
        required_capabilities: List[str],
        tenant_id: uuid.UUID,
        exclude_agent_ids: List[uuid.UUID] = None
    ) -> Optional[Agent]:
        """
        Find the best agent in a group for given capabilities.

        Args:
            group_id: The agent group to search in
            required_capabilities: List of capabilities needed
            tenant_id: Tenant ID for security
            exclude_agent_ids: Agents to exclude (e.g., already tried)

        Returns:
            Best matching Agent or None
        """
        # Get all agents in this group via relationships
        relationships = self.db.query(AgentRelationship).filter(
            AgentRelationship.group_id == group_id
        ).all()

        # Collect unique agent IDs
        agent_ids = set()
        for rel in relationships:
            agent_ids.add(rel.from_agent_id)
            agent_ids.add(rel.to_agent_id)

        if exclude_agent_ids:
            agent_ids -= set(exclude_agent_ids)

        if not agent_ids:
            return None

        # Get agents with their capabilities
        agents = self.db.query(Agent).filter(
            Agent.id.in_(agent_ids),
            Agent.tenant_id == tenant_id
        ).all()

        # Score agents based on capability match
        best_agent = None
        best_score = -1

        for agent in agents:
            score = self._calculate_capability_score(agent, required_capabilities)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    def _calculate_capability_score(self, agent: Agent, required_capabilities: List[str]) -> float:
        """Calculate how well an agent matches required capabilities."""
        if not agent.capabilities:
            return 0.0

        agent_caps = set(agent.capabilities)
        required_caps = set(required_capabilities)

        if not required_caps:
            return 1.0

        # Count matches
        matches = len(agent_caps & required_caps)
        return matches / len(required_caps)

    def get_supervisor(self, agent_id: uuid.UUID, group_id: uuid.UUID) -> Optional[Agent]:
        """Get the supervisor agent for a given agent in a group."""
        rel = self.db.query(AgentRelationship).filter(
            AgentRelationship.group_id == group_id,
            AgentRelationship.to_agent_id == agent_id,
            AgentRelationship.relationship_type == "supervises"
        ).first()

        if rel:
            return self.db.query(Agent).filter(Agent.id == rel.from_agent_id).first()
        return None

    def get_subordinates(self, agent_id: uuid.UUID, group_id: uuid.UUID) -> List[Agent]:
        """Get agents supervised by a given agent."""
        rels = self.db.query(AgentRelationship).filter(
            AgentRelationship.group_id == group_id,
            AgentRelationship.from_agent_id == agent_id,
            AgentRelationship.relationship_type == "supervises"
        ).all()

        subordinate_ids = [rel.to_agent_id for rel in rels]
        if not subordinate_ids:
            return []

        return self.db.query(Agent).filter(Agent.id.in_(subordinate_ids)).all()

    def can_delegate(self, from_agent: Agent, to_agent: Agent, group_id: uuid.UUID) -> bool:
        """Check if one agent can delegate to another."""
        rel = self.db.query(AgentRelationship).filter(
            AgentRelationship.group_id == group_id,
            AgentRelationship.from_agent_id == from_agent.id,
            AgentRelationship.to_agent_id == to_agent.id,
            AgentRelationship.relationship_type.in_(["supervises", "delegates_to"])
        ).first()

        return rel is not None
```

**Step 3: Run tests**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py::test_task_dispatcher_assigns_to_best_agent -v
```

**Step 4: Commit**

```bash
git add apps/api/app/services/orchestration/ apps/api/tests/test_agent_orchestration.py
git commit -m "feat(orchestration): add TaskDispatcher service for routing tasks"
```

---

## Task 10: Run All Tests and Final Commit

**Step 1: Run complete test suite**

```bash
cd apps/api && pytest tests/test_agent_orchestration.py -v
```

Expected: All tests PASS

**Step 2: Run existing tests to ensure no regressions**

```bash
cd apps/api && pytest tests/ -v
```

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat(orchestration): complete Phase 1 - Agent Orchestration models and services

- Extended Agent model with role, capabilities, personality, autonomy
- Added AgentGroup model for multi-agent teams
- Added AgentRelationship model for hierarchy and collaboration
- Added AgentTask model for work tracking
- Added AgentMessage model for inter-agent communication
- Added AgentSkill model for learnable capabilities
- Added API routes for agent_groups and tasks
- Added TaskDispatcher service for intelligent task routing

Part of Enterprise AI Platform - see docs/plans/2025-11-25-enterprise-ai-platform-design.md"
```

---

## Verification Checklist

After completing all tasks:

- [ ] All new models created and imported in init_db.py
- [ ] All schemas created with proper validation
- [ ] API routes registered in routes.py
- [ ] All tests passing
- [ ] No regressions in existing tests
- [ ] Code committed with descriptive messages

## Next Phase

After Phase 1 is complete, proceed to **Phase 2: Memory System** which will add:
- AgentMemory model
- KnowledgeEntity and KnowledgeRelation models
- MemoryService with three-tier storage
- Memory API routes

---

**Plan complete.** This document contains 10 bite-sized tasks with exact file paths, complete code, and test commands.
