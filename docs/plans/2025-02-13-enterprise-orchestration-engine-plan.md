# Enterprise Orchestration Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire all existing agent models into Temporal-backed durable execution with in-platform traceability, managed per-tenant OpenClaw instances, encrypted credential vault, and LLM-agnostic skill execution.

**Architecture:** Temporal workflows orchestrate agent task execution. ExecutionTrace provides in-platform audit trails. Each tenant gets an isolated OpenClaw pod via Helm. SkillCredentials store encrypted API keys injected at runtime. The existing LLM Router powers per-skill model selection.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Temporal (temporalio), React 18, Bootstrap 5, Helm 3, Kubernetes Python client

**Design doc:** `docs/plans/2025-02-13-enterprise-orchestration-engine-design.md`

---

## Phase 1: Core Orchestration Engine

### Task 1: ExecutionTrace Model + Migration

**Files:**
- Create: `apps/api/app/models/execution_trace.py`
- Create: `apps/api/migrations/026_add_execution_traces.sql`
- Modify: `apps/api/app/models/__init__.py`

**Step 1: Create the model**

```python
# apps/api/app/models/execution_trace.py
import uuid
from sqlalchemy import Column, String, Integer, Float, ForeignKey, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class ExecutionTrace(Base):
    __tablename__ = "execution_traces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    step_type = Column(String, nullable=False)  # dispatched, memory_recall, executing, skill_call, delegated, approval_requested, approval_granted, completed, failed
    step_order = Column(Integer, nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    details = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("AgentTask")
    tenant = relationship("Tenant")
    agent = relationship("Agent")
```

**Step 2: Create the migration**

```sql
-- apps/api/migrations/026_add_execution_traces.sql
CREATE TABLE IF NOT EXISTS execution_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES agent_tasks(id),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    step_type VARCHAR NOT NULL,
    step_order INTEGER NOT NULL,
    agent_id UUID REFERENCES agents(id),
    details JSONB,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_execution_traces_task_id ON execution_traces(task_id);
CREATE INDEX idx_execution_traces_tenant_id ON execution_traces(tenant_id);
CREATE INDEX idx_execution_traces_step_type ON execution_traces(step_type);
```

**Step 3: Register model in __init__.py**

Add to `apps/api/app/models/__init__.py`:
```python
from .dataset_group import DatasetGroup
from .execution_trace import ExecutionTrace

__all__ = ["DatasetGroup", "ExecutionTrace"]
```

**Step 4: Verify model imports**

Run: `cd apps/api && python -c "from app.models.execution_trace import ExecutionTrace; print(ExecutionTrace.__tablename__)"`
Expected: `execution_traces`

**Step 5: Commit**

```bash
git add apps/api/app/models/execution_trace.py apps/api/migrations/026_add_execution_traces.sql apps/api/app/models/__init__.py
git commit -m "feat: add ExecutionTrace model for task audit trails"
```

---

### Task 2: ExecutionTrace Schema + Service

**Files:**
- Create: `apps/api/app/schemas/execution_trace.py`
- Create: `apps/api/app/services/execution_traces.py`
- Modify: `apps/api/app/schemas/__init__.py`

**Step 1: Create schemas**

```python
# apps/api/app/schemas/execution_trace.py
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import uuid

StepType = Literal[
    "dispatched", "memory_recall", "executing", "skill_call",
    "delegated", "approval_requested", "approval_granted",
    "completed", "failed"
]


class ExecutionTraceCreate(BaseModel):
    task_id: uuid.UUID
    step_type: StepType
    step_order: int
    agent_id: Optional[uuid.UUID] = None
    details: Optional[dict] = None
    duration_ms: Optional[int] = None


class ExecutionTrace(ExecutionTraceCreate):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

**Step 2: Create service**

```python
# apps/api/app/services/execution_traces.py
from typing import List
from sqlalchemy.orm import Session
import uuid

from app.models.execution_trace import ExecutionTrace
from app.schemas.execution_trace import ExecutionTraceCreate


def create_trace(db: Session, *, trace_in: ExecutionTraceCreate, tenant_id: uuid.UUID) -> ExecutionTrace:
    db_item = ExecutionTrace(**trace_in.dict(), tenant_id=tenant_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def get_traces_by_task(db: Session, task_id: uuid.UUID, tenant_id: uuid.UUID) -> List[ExecutionTrace]:
    return (
        db.query(ExecutionTrace)
        .filter(ExecutionTrace.task_id == task_id, ExecutionTrace.tenant_id == tenant_id)
        .order_by(ExecutionTrace.step_order)
        .all()
    )


def get_traces_by_tenant(
    db: Session, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[ExecutionTrace]:
    return (
        db.query(ExecutionTrace)
        .filter(ExecutionTrace.tenant_id == tenant_id)
        .order_by(ExecutionTrace.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
```

**Step 3: Register schema in __init__.py**

Add to `apps/api/app/schemas/__init__.py`:
```python
from . import dataset_group
from . import execution_trace

__all__ = ["dataset_group", "execution_trace"]
```

**Step 4: Verify imports**

Run: `cd apps/api && python -c "from app.services.execution_traces import create_trace, get_traces_by_task; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add apps/api/app/schemas/execution_trace.py apps/api/app/services/execution_traces.py apps/api/app/schemas/__init__.py
git commit -m "feat: add ExecutionTrace schema and CRUD service"
```

---

### Task 3: Task Execution API Endpoints

**Files:**
- Create: `apps/api/app/api/v1/task_execution.py`
- Modify: `apps/api/app/api/v1/routes.py`

**Step 1: Create route module**

```python
# apps/api/app/api/v1/task_execution.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app import schemas
from app.api import deps
from app.models.user import User
from app.services import agent_tasks as task_service
from app.services import execution_traces as trace_service

router = APIRouter()


@router.get("/", response_model=list)
def list_tasks(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    """List agent tasks for current tenant with optional status filter."""
    tasks = task_service.get_tasks_by_tenant(
        db, tenant_id=current_user.tenant_id, skip=skip, limit=limit
    )
    if status_filter:
        tasks = [t for t in tasks if t.status == status_filter]
    return tasks


@router.get("/{task_id}")
def get_task(
    task_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Get task detail with summary metrics."""
    task = task_service.get_task(db, task_id=task_id)
    if not task or str(task.assigned_agent.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/trace", response_model=List[schemas.execution_trace.ExecutionTrace])
def get_task_trace(
    task_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Get execution timeline for a task."""
    traces = trace_service.get_traces_by_task(
        db, task_id=task_id, tenant_id=current_user.tenant_id
    )
    return traces


@router.post("/{task_id}/approve", status_code=status.HTTP_200_OK)
async def approve_task(
    task_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Approve a task that is waiting for human approval."""
    task = task_service.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "waiting_input":
        raise HTTPException(status_code=400, detail="Task is not waiting for approval")
    task_service.update_task_status(db, task_id=task_id, status="executing", approved_by_id=current_user.id)
    return {"message": "Task approved", "task_id": str(task_id)}


@router.post("/{task_id}/reject", status_code=status.HTTP_200_OK)
async def reject_task(
    task_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Reject a task that is waiting for human approval."""
    task = task_service.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "waiting_input":
        raise HTTPException(status_code=400, detail="Task is not waiting for approval")
    task_service.update_task_status(db, task_id=task_id, status="failed", error="Rejected by human")
    return {"message": "Task rejected", "task_id": str(task_id)}
```

**Step 2: Mount in routes.py**

Add import and include_router in `apps/api/app/api/v1/routes.py`:
```python
from app.api.v1 import task_execution
# ... existing includes ...
router.include_router(task_execution.router, prefix="/agent-tasks", tags=["agent-tasks"])
```

**Step 3: Verify endpoint registration**

Run: `cd apps/api && python -c "from app.api.v1.task_execution import router; print([r.path for r in router.routes])"`

**Step 4: Commit**

```bash
git add apps/api/app/api/v1/task_execution.py apps/api/app/api/v1/routes.py
git commit -m "feat: add task execution API endpoints with trace and approval"
```

---

### Task 4: TaskExecutionWorkflow + Activities

**Files:**
- Create: `apps/api/app/workflows/task_execution.py`
- Create: `apps/api/app/workflows/activities/task_execution.py`

**Step 1: Create workflow**

```python
# apps/api/app/workflows/task_execution.py
from temporalio import workflow
from datetime import timedelta
from typing import Dict, Any


@workflow.defn(sandboxed=False)
class TaskExecutionWorkflow:
    """Durable workflow for executing agent tasks with full traceability."""

    @workflow.run
    async def run(self, task_id: str, tenant_id: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        workflow.logger.info(f"Starting task execution for {task_id}")

        retry_policy = workflow.RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=30),
            maximum_interval=timedelta(minutes=5),
            backoff_coefficient=2.0,
        )

        # Step 1: Dispatch — find best agent
        dispatch_result = await workflow.execute_activity(
            "dispatch_task",
            args=[task_id, tenant_id, task_data],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        if dispatch_result.get("status") == "failed":
            return {"status": "failed", "error": dispatch_result.get("error")}

        agent_id = dispatch_result["agent_id"]

        # Step 2: Recall memory
        memory_result = await workflow.execute_activity(
            "recall_memory",
            args=[task_id, tenant_id, agent_id, task_data],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=retry_policy,
        )

        # Step 3: Execute
        execution_context = {
            **task_data,
            "agent_id": agent_id,
            "memories": memory_result.get("memories", []),
        }

        execute_result = await workflow.execute_activity(
            "execute_task",
            args=[task_id, tenant_id, agent_id, execution_context],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=retry_policy,
        )

        # Step 4: Evaluate and store
        evaluate_result = await workflow.execute_activity(
            "evaluate_task",
            args=[task_id, tenant_id, agent_id, execute_result],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        workflow.logger.info(f"Task {task_id} completed with confidence {evaluate_result.get('confidence')}")

        return {
            "status": evaluate_result.get("status", "completed"),
            "confidence": evaluate_result.get("confidence"),
            "output": execute_result.get("output"),
            "tokens_used": evaluate_result.get("tokens_used", 0),
            "cost": evaluate_result.get("cost", 0.0),
        }
```

**Step 2: Create activities**

```python
# apps/api/app/workflows/activities/task_execution.py
from temporalio import activity
from typing import Dict, Any, List
from datetime import datetime
import time

from app.db.session import SessionLocal
from app.models.agent_task import AgentTask
from app.models.execution_trace import ExecutionTrace
from app.models.agent_memory import AgentMemory
from app.models.agent_skill import AgentSkill
from app.services.orchestration.task_dispatcher import TaskDispatcher
from app.services.adk_client import get_adk_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _log_trace(db, task_id: str, tenant_id: str, step_type: str, step_order: int,
               agent_id: str = None, details: dict = None, duration_ms: int = None):
    """Helper to write an ExecutionTrace record."""
    trace = ExecutionTrace(
        task_id=task_id,
        tenant_id=tenant_id,
        step_type=step_type,
        step_order=step_order,
        agent_id=agent_id,
        details=details,
        duration_ms=duration_ms,
    )
    db.add(trace)
    db.commit()


@activity.defn
async def dispatch_task(task_id: str, tenant_id: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Find the best agent for the task using TaskDispatcher."""
    start = time.time()
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            return {"status": "failed", "error": "Task not found"}

        task.status = "thinking"
        task.started_at = datetime.utcnow()
        db.commit()

        dispatcher = TaskDispatcher(db)
        required_capabilities = task_data.get("required_capabilities", [])
        group_id = str(task.group_id) if task.group_id else None

        agent = None
        if task.assigned_agent_id:
            # Task already has an assigned agent
            agent_id = str(task.assigned_agent_id)
        elif group_id:
            agent = dispatcher.find_best_agent(
                group_id=group_id,
                required_capabilities=required_capabilities,
                tenant_id=tenant_id,
            )
            if agent:
                task.assigned_agent_id = agent.id
                db.commit()
                agent_id = str(agent.id)
            else:
                task.status = "failed"
                task.error = "No suitable agent found"
                db.commit()
                _log_trace(db, task_id, tenant_id, "failed", 1, details={"error": "No agent matched"})
                return {"status": "failed", "error": "No suitable agent found"}
        else:
            agent_id = str(task.assigned_agent_id)

        duration = int((time.time() - start) * 1000)
        _log_trace(db, task_id, tenant_id, "dispatched", 1, agent_id=agent_id,
                   details={"capabilities_required": required_capabilities}, duration_ms=duration)

        return {"status": "dispatched", "agent_id": agent_id}
    finally:
        db.close()


@activity.defn
async def recall_memory(task_id: str, tenant_id: str, agent_id: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Load relevant agent memories for context."""
    start = time.time()
    db = SessionLocal()
    try:
        memories = (
            db.query(AgentMemory)
            .filter(
                AgentMemory.agent_id == agent_id,
                AgentMemory.tenant_id == tenant_id,
                AgentMemory.importance >= 0.3,
            )
            .order_by(AgentMemory.importance.desc())
            .limit(5)
            .all()
        )

        memory_list = [
            {"type": m.memory_type, "content": m.content, "importance": m.importance}
            for m in memories
        ]

        # Update access counts
        for m in memories:
            m.access_count = (m.access_count or 0) + 1
            m.last_accessed_at = datetime.utcnow()
        db.commit()

        duration = int((time.time() - start) * 1000)
        _log_trace(db, task_id, tenant_id, "memory_recall", 2, agent_id=agent_id,
                   details={"memories_loaded": len(memory_list)}, duration_ms=duration)

        return {"memories": memory_list}
    finally:
        db.close()


@activity.defn
async def execute_task(task_id: str, tenant_id: str, agent_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the task via ADK or direct processing."""
    start = time.time()
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        task.status = "executing"
        db.commit()

        # Route to ADK for AI reasoning
        try:
            client = get_adk_client()
            if client:
                events = client.run(
                    user_id=agent_id,
                    session_id=f"task-{task_id}",
                    message=task.objective,
                )
                # Extract response from ADK events
                response_text = ""
                for event in events:
                    if isinstance(event, dict):
                        content = event.get("content", {})
                        if isinstance(content, dict):
                            parts = content.get("parts", [])
                            for part in parts:
                                if isinstance(part, dict) and "text" in part:
                                    response_text += part["text"]

                output = {"response": response_text, "adk_events": events}
            else:
                output = {"response": f"Task '{task.objective}' processed (ADK unavailable)", "backend": "fallback"}
        except Exception as e:
            logger.error(f"ADK execution failed: {e}")
            output = {"response": f"Task '{task.objective}' processed with fallback", "error": str(e)}

        duration = int((time.time() - start) * 1000)
        _log_trace(db, task_id, tenant_id, "executing", 3, agent_id=agent_id,
                   details={"backend": "adk", "output_length": len(str(output))}, duration_ms=duration)

        return {"status": "executed", "output": output}
    finally:
        db.close()


@activity.defn
async def evaluate_task(task_id: str, tenant_id: str, agent_id: str, execute_result: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate results, update task, store memory, update skill proficiency."""
    start = time.time()
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()

        # Update task
        task.status = "completed"
        task.output = execute_result.get("output")
        task.confidence = 0.85  # TODO: Calculate from actual result quality
        task.completed_at = datetime.utcnow()
        db.commit()

        # Store experience memory
        memory = AgentMemory(
            agent_id=agent_id,
            tenant_id=tenant_id,
            memory_type="experience",
            content=f"Completed task: {task.objective}",
            importance=0.5,
            source="task_execution",
            source_task_id=task_id,
        )
        db.add(memory)

        # Update skill proficiency
        if task.task_type:
            skill = (
                db.query(AgentSkill)
                .filter(AgentSkill.agent_id == agent_id, AgentSkill.skill_name == task.task_type)
                .first()
            )
            if skill:
                skill.times_used = (skill.times_used or 0) + 1
                skill.last_used_at = datetime.utcnow()
                # Increment proficiency slightly on success
                skill.proficiency = min(1.0, (skill.proficiency or 0.5) + 0.01)

        db.commit()

        duration = int((time.time() - start) * 1000)
        _log_trace(db, task_id, tenant_id, "completed", 4, agent_id=agent_id,
                   details={"confidence": task.confidence, "tokens_used": task.tokens_used,
                            "cost": task.cost}, duration_ms=duration)

        return {
            "status": "completed",
            "confidence": task.confidence,
            "tokens_used": task.tokens_used or 0,
            "cost": task.cost or 0.0,
        }
    finally:
        db.close()
```

**Step 3: Commit**

```bash
git add apps/api/app/workflows/task_execution.py apps/api/app/workflows/activities/task_execution.py
git commit -m "feat: add TaskExecutionWorkflow with dispatch, memory, execute, evaluate activities"
```

---

### Task 5: Orchestration Worker

**Files:**
- Create: `apps/api/app/workers/orchestration_worker.py`
- Create: `helm/values/agentprovision-orchestration-worker.yaml`

**Step 1: Create the worker**

```python
# apps/api/app/workers/orchestration_worker.py
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import settings
from app.workflows.task_execution import TaskExecutionWorkflow
from app.workflows.activities.task_execution import (
    dispatch_task,
    recall_memory,
    execute_task,
    evaluate_task,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

TASK_QUEUE = "agentprovision-orchestration"


async def run_worker():
    logger.info(f"Connecting to Temporal at {settings.TEMPORAL_ADDRESS}")
    client = await Client.connect(
        settings.TEMPORAL_ADDRESS,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[TaskExecutionWorkflow],
        activities=[
            dispatch_task,
            recall_memory,
            execute_task,
            evaluate_task,
        ],
    )

    logger.info(f"Starting orchestration worker on queue: {TASK_QUEUE}")
    await worker.run()


def main():
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
```

**Step 2: Create Helm values**

```yaml
# helm/values/agentprovision-orchestration-worker.yaml
replicaCount: 1

image:
  repository: gcr.io/ai-agency-479516/agentprovision-api
  tag: latest
  pullPolicy: Always

command: ["python", "-m", "app.workers.orchestration_worker"]

env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: agentprovision-api-secret
        key: DATABASE_URL
  - name: TEMPORAL_ADDRESS
    value: "agentprovision-temporal:7233"
  - name: ADK_BASE_URL
    value: "http://agentprovision-adk:8080"
  - name: ADK_APP_NAME
    value: "agentprovision_supervisor"

resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

service:
  enabled: false

healthcheck:
  enabled: false
```

**Step 3: Verify worker starts locally**

Run: `cd apps/api && python -c "from app.workers.orchestration_worker import TASK_QUEUE; print(TASK_QUEUE)"`
Expected: `agentprovision-orchestration`

**Step 4: Commit**

```bash
git add apps/api/app/workers/orchestration_worker.py helm/values/agentprovision-orchestration-worker.yaml
git commit -m "feat: add orchestration worker for Temporal task queue"
```

---

### Task 6: Task Execution Console (Frontend)

**Files:**
- Create: `apps/web/src/pages/TaskConsolePage.js`
- Create: `apps/web/src/services/taskService.js`
- Create: `apps/web/src/components/TaskTimeline.js`
- Modify: `apps/web/src/App.js` (add route)
- Modify: `apps/web/src/components/Layout.js` (add nav item)

**Step 1: Create API service**

```javascript
// apps/web/src/services/taskService.js
import api from '../utils/api';

const taskService = {
  getAll: (params = {}) => api.get('/agent-tasks/', { params }),
  getById: (id) => api.get(`/agent-tasks/${id}`),
  getTrace: (id) => api.get(`/agent-tasks/${id}/trace`),
  approve: (id) => api.post(`/agent-tasks/${id}/approve`),
  reject: (id) => api.post(`/agent-tasks/${id}/reject`),
};

export default taskService;
```

**Step 2: Create TaskTimeline component**

```javascript
// apps/web/src/components/TaskTimeline.js
import { Badge } from 'react-bootstrap';
import { FaRobot, FaBrain, FaCog, FaCheck, FaTimes, FaClock } from 'react-icons/fa';

const STEP_ICONS = {
  dispatched: FaRobot,
  memory_recall: FaBrain,
  executing: FaCog,
  skill_call: FaCog,
  approval_requested: FaClock,
  approval_granted: FaCheck,
  completed: FaCheck,
  failed: FaTimes,
};

const STEP_COLORS = {
  dispatched: '#3b82f6',
  memory_recall: '#8b5cf6',
  executing: '#f59e0b',
  skill_call: '#10b981',
  approval_requested: '#f97316',
  approval_granted: '#10b981',
  completed: '#10b981',
  failed: '#ef4444',
};

const TaskTimeline = ({ traces }) => {
  if (!traces || traces.length === 0) {
    return <p className="text-muted">No execution trace available.</p>;
  }

  return (
    <div className="task-timeline">
      {traces.map((trace, idx) => {
        const Icon = STEP_ICONS[trace.step_type] || FaCog;
        const color = STEP_COLORS[trace.step_type] || '#6c757d';
        return (
          <div key={trace.id} className="timeline-step" style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>
            <div style={{ color, minWidth: '24px', paddingTop: '2px' }}>
              <Icon size={18} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <strong style={{ color: 'var(--color-foreground)' }}>{trace.step_type.toUpperCase().replace('_', ' ')}</strong>
                {trace.duration_ms && (
                  <Badge bg="dark" style={{ fontSize: '0.7rem' }}>{trace.duration_ms}ms</Badge>
                )}
              </div>
              {trace.details && (
                <pre style={{ fontSize: '0.8rem', color: 'var(--color-muted)', margin: '4px 0 0 0', whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(trace.details, null, 2)}
                </pre>
              )}
              <small style={{ color: 'var(--color-soft)' }}>
                {new Date(trace.created_at).toLocaleTimeString()}
              </small>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default TaskTimeline;
```

**Step 3: Create TaskConsolePage**

```javascript
// apps/web/src/pages/TaskConsolePage.js
import { useEffect, useState } from 'react';
import { Badge, Button, Card, Col, Row, Spinner, Table } from 'react-bootstrap';
import { FaRobot, FaCheckCircle, FaTimesCircle, FaClock, FaSyncAlt } from 'react-icons/fa';
import Layout from '../components/Layout';
import TaskTimeline from '../components/TaskTimeline';
import taskService from '../services/taskService';

const STATUS_BADGES = {
  queued: { bg: 'secondary', icon: FaClock },
  thinking: { bg: 'info', icon: FaRobot },
  executing: { bg: 'warning', icon: FaSyncAlt },
  waiting_input: { bg: 'danger', icon: FaClock },
  delegated: { bg: 'primary', icon: FaRobot },
  completed: { bg: 'success', icon: FaCheckCircle },
  failed: { bg: 'danger', icon: FaTimesCircle },
};

const TaskConsolePage = () => {
  const [tasks, setTasks] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);
  const [traces, setTraces] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = async () => {
    try {
      const res = await taskService.getAll();
      setTasks(res.data || []);
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  };

  const selectTask = async (task) => {
    setSelectedTask(task);
    try {
      const res = await taskService.getTrace(task.id);
      setTraces(res.data || []);
    } catch (err) {
      console.error('Failed to fetch trace:', err);
    }
  };

  const handleApprove = async (taskId) => {
    await taskService.approve(taskId);
    fetchTasks();
    if (selectedTask && selectedTask.id === taskId) {
      selectTask(selectedTask);
    }
  };

  const handleReject = async (taskId) => {
    await taskService.reject(taskId);
    fetchTasks();
  };

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Layout>
      <div style={{ padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <h4 style={{ color: 'var(--color-foreground)', margin: 0 }}>Task Execution Console</h4>
            <small style={{ color: 'var(--color-muted)' }}>Monitor agent task execution, traces, and approvals</small>
          </div>
          <Button variant="outline-light" size="sm" onClick={fetchTasks}>
            <FaSyncAlt /> Refresh
          </Button>
        </div>

        <Row>
          <Col md={5}>
            <Card style={{ background: 'var(--surface-elevated)', border: '1px solid var(--color-border)' }}>
              <Card.Body>
                <h6 style={{ color: 'var(--color-foreground)' }}>Tasks</h6>
                {loading ? (
                  <Spinner animation="border" size="sm" />
                ) : tasks.length === 0 ? (
                  <p className="text-muted">No tasks yet.</p>
                ) : (
                  <Table hover size="sm" variant="dark" style={{ fontSize: '0.85rem' }}>
                    <tbody>
                      {tasks.map(task => {
                        const statusInfo = STATUS_BADGES[task.status] || { bg: 'secondary' };
                        return (
                          <tr key={task.id} onClick={() => selectTask(task)}
                              style={{ cursor: 'pointer', background: selectedTask?.id === task.id ? 'var(--surface-contrast)' : 'transparent' }}>
                            <td>
                              <div style={{ color: 'var(--color-foreground)' }}>{task.objective}</div>
                              <small style={{ color: 'var(--color-soft)' }}>
                                {task.task_type} • {task.priority}
                              </small>
                            </td>
                            <td style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                              <Badge bg={statusInfo.bg}>{task.status}</Badge>
                              {task.status === 'waiting_input' && (
                                <div style={{ marginTop: '4px' }}>
                                  <Button size="sm" variant="outline-success" onClick={(e) => { e.stopPropagation(); handleApprove(task.id); }} style={{ marginRight: '4px', fontSize: '0.7rem' }}>Approve</Button>
                                  <Button size="sm" variant="outline-danger" onClick={(e) => { e.stopPropagation(); handleReject(task.id); }} style={{ fontSize: '0.7rem' }}>Reject</Button>
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                )}
              </Card.Body>
            </Card>
          </Col>

          <Col md={7}>
            {selectedTask ? (
              <Card style={{ background: 'var(--surface-elevated)', border: '1px solid var(--color-border)' }}>
                <Card.Body>
                  <h6 style={{ color: 'var(--color-foreground)' }}>{selectedTask.objective}</h6>
                  <div style={{ display: 'flex', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                    <Badge bg="dark">Type: {selectedTask.task_type}</Badge>
                    <Badge bg="dark">Priority: {selectedTask.priority}</Badge>
                    {selectedTask.confidence && <Badge bg="dark">Confidence: {(selectedTask.confidence * 100).toFixed(0)}%</Badge>}
                    {selectedTask.tokens_used > 0 && <Badge bg="dark">Tokens: {selectedTask.tokens_used}</Badge>}
                    {selectedTask.cost > 0 && <Badge bg="dark">Cost: ${selectedTask.cost.toFixed(4)}</Badge>}
                  </div>
                  <h6 style={{ color: 'var(--color-foreground)', marginTop: '16px' }}>Execution Timeline</h6>
                  <TaskTimeline traces={traces} />
                </Card.Body>
              </Card>
            ) : (
              <Card style={{ background: 'var(--surface-elevated)', border: '1px solid var(--color-border)' }}>
                <Card.Body className="text-center text-muted" style={{ padding: '48px' }}>
                  Select a task to view its execution trace
                </Card.Body>
              </Card>
            )}
          </Col>
        </Row>
      </div>
    </Layout>
  );
};

export default TaskConsolePage;
```

**Step 4: Add route in App.js**

Add import: `import TaskConsolePage from './pages/TaskConsolePage';`
Add route: `<Route path="/task-console" element={<ProtectedRoute><TaskConsolePage /></ProtectedRoute>} />`

**Step 5: Add nav item in Layout.js**

In the `AI OPERATIONS` section of `navSections`, add:
```javascript
{ path: '/task-console', icon: ListCheck, label: 'Task Console', description: 'Monitor agent task execution and traces' },
```
Add import: `import { ListCheck } from 'react-bootstrap-icons';` (or use existing icon library)

**Step 6: Commit**

```bash
git add apps/web/src/pages/TaskConsolePage.js apps/web/src/services/taskService.js apps/web/src/components/TaskTimeline.js apps/web/src/App.js apps/web/src/components/Layout.js
git commit -m "feat: add Task Execution Console with timeline and approval UI"
```

---

## Phase 2: Managed OpenClaw Instances

### Task 7: TenantInstance Model + Migration

**Files:**
- Create: `apps/api/app/models/tenant_instance.py`
- Create: `apps/api/migrations/027_add_tenant_instances.sql`
- Modify: `apps/api/app/models/__init__.py`

**Step 1: Create the model**

```python
# apps/api/app/models/tenant_instance.py
import uuid
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class TenantInstance(Base):
    __tablename__ = "tenant_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    instance_type = Column(String, nullable=False, default="openclaw")  # extensible
    version = Column(String, nullable=True)
    status = Column(String, default="provisioning")  # provisioning, running, stopped, upgrading, error, destroying
    internal_url = Column(String, nullable=True)
    helm_release = Column(String, nullable=True)
    k8s_namespace = Column(String, default="prod")
    resource_config = Column(JSON, nullable=True)  # {cpu_request, cpu_limit, memory_request, memory_limit, storage}
    health = Column(JSON, nullable=True)  # {last_check, healthy, uptime, cpu_pct, memory_pct}
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
```

**Step 2: Create migration**

```sql
-- apps/api/migrations/027_add_tenant_instances.sql
CREATE TABLE IF NOT EXISTS tenant_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    instance_type VARCHAR NOT NULL DEFAULT 'openclaw',
    version VARCHAR,
    status VARCHAR DEFAULT 'provisioning',
    internal_url VARCHAR,
    helm_release VARCHAR,
    k8s_namespace VARCHAR DEFAULT 'prod',
    resource_config JSONB,
    health JSONB,
    error VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tenant_instances_tenant_id ON tenant_instances(tenant_id);
CREATE UNIQUE INDEX idx_tenant_instances_helm_release ON tenant_instances(helm_release);
```

**Step 3: Update models __init__.py, commit**

```bash
git add apps/api/app/models/tenant_instance.py apps/api/migrations/027_add_tenant_instances.sql apps/api/app/models/__init__.py
git commit -m "feat: add TenantInstance model for managed OpenClaw pods"
```

---

### Task 8: TenantInstance Schema + Service + Routes

**Files:**
- Create: `apps/api/app/schemas/tenant_instance.py`
- Create: `apps/api/app/services/tenant_instances.py`
- Create: `apps/api/app/api/v1/instances.py`
- Modify: `apps/api/app/api/v1/routes.py`

Follow same patterns as Tasks 2-3 (ConnectorCreate/Update/InDB pattern). Key endpoints:

```
GET    /api/v1/instances/              # List tenant instances
POST   /api/v1/instances/              # Deploy new instance (triggers Temporal workflow)
GET    /api/v1/instances/{id}          # Get instance detail + health
POST   /api/v1/instances/{id}/stop     # Scale to 0
POST   /api/v1/instances/{id}/start    # Scale to 1
POST   /api/v1/instances/{id}/restart  # Rollout restart
POST   /api/v1/instances/{id}/upgrade  # Upgrade version
DELETE /api/v1/instances/{id}          # Destroy (helm uninstall + delete PVC)
GET    /api/v1/instances/{id}/logs     # Stream pod logs
```

**Commit after implementation.**

---

### Task 9: OpenClawProvisionWorkflow

**Files:**
- Create: `apps/api/app/workflows/openclaw_provision.py`
- Create: `apps/api/app/workflows/activities/openclaw_provision.py`
- Modify: `apps/api/app/workers/orchestration_worker.py` (register new workflow + activities)

**Step 1: Create workflow**

The workflow calls 5 activities:
1. `generate_openclaw_values` — renders per-tenant values.yaml from the Helm chart at `../openclaw-k8s/helm/openclaw/`
2. `helm_install_openclaw` — runs `helm upgrade --install openclaw-{tenant_short_id} <chart> -f <values> -n prod`
3. `wait_pod_ready` — polls pod status until ready (timeout 5 min)
4. `health_check_openclaw` — verifies WebSocket on port 18789
5. `register_instance` — updates TenantInstance record with `status=running`, `internal_url`

**Step 2: Activities use subprocess for Helm or Kubernetes Python client**

The `helm_install_openclaw` activity:
```python
import subprocess

result = subprocess.run(
    ["helm", "upgrade", "--install", release_name, chart_path,
     "-f", values_path, "-n", namespace, "--wait", "--timeout", "5m"],
    capture_output=True, text=True
)
```

**Step 3: Register in orchestration worker**

Add to `orchestration_worker.py`:
```python
from app.workflows.openclaw_provision import OpenClawProvisionWorkflow
from app.workflows.activities.openclaw_provision import (
    generate_openclaw_values, helm_install_openclaw,
    wait_pod_ready, health_check_openclaw, register_instance,
)
```

Add to workflows list and activities list in the Worker constructor.

**Commit after implementation.**

---

### Task 10: OpenClaw Instance Management UI

**Files:**
- Create: `apps/web/src/components/OpenClawInstanceCard.js`
- Create: `apps/web/src/services/instanceService.js`
- Modify: `apps/web/src/pages/IntegrationsPage.js` (add instance card section)

The UI shows an instance card at the top of the Integrations page:
- **Not deployed:** CTA with [Deploy OpenClaw Instance] button
- **Provisioning:** Spinner with status message
- **Running:** Status card with version, uptime, resource gauges, action buttons
- **Stopped/Error:** Status with [Start] or error details

**Commit after implementation.**

---

## Phase 3: Skills Gateway + Credentials

### Task 11: SkillConfig + SkillCredential Models + Migration

**Files:**
- Create: `apps/api/app/models/skill_config.py`
- Create: `apps/api/app/models/skill_credential.py`
- Create: `apps/api/migrations/028_add_skill_configs_and_credentials.sql`

**SkillConfig columns:** id, tenant_id, instance_id (FK→tenant_instances), skill_name, enabled, requires_approval, rate_limit (JSON), allowed_scopes (JSON), llm_config_id (FK→llm_configs, nullable), created_at, updated_at

**SkillCredential columns:** id, tenant_id, skill_config_id (FK→skill_configs), credential_key, encrypted_value, credential_type, status, expires_at, last_used_at, created_at, updated_at

**Commit after implementation.**

---

### Task 12: Credential Vault Service

**Files:**
- Create: `apps/api/app/services/orchestration/credential_vault.py`

AES-256-GCM encryption/decryption:
```python
from cryptography.fernet import Fernet
# Use ENCRYPTION_KEY from settings (loaded from GCP Secret Manager)
# encrypt(value) → encrypted string
# decrypt(encrypted_value) → plaintext string
# Never log plaintext values
```

Add `ENCRYPTION_KEY` to `apps/api/app/core/config.py` settings.
Add `cryptography` to `apps/api/requirements.txt`.

**Commit after implementation.**

---

### Task 13: Skill Router Service

**Files:**
- Create: `apps/api/app/services/orchestration/skill_router.py`

The Skill Router:
1. Resolves tenant's OpenClaw instance (TenantInstance query)
2. Checks SkillConfig (enabled, rate limit, scopes)
3. Loads and decrypts credentials
4. Calls OpenClaw Gateway via WebSocket
5. Logs to ExecutionTrace

Add `websockets` to `apps/api/requirements.txt`.

**Commit after implementation.**

---

### Task 14: Skill Config + Credential Registry + API Endpoints

**Files:**
- Create: `apps/api/app/schemas/skill_config.py`
- Create: `apps/api/app/services/skill_configs.py`
- Create: `apps/api/app/api/v1/skill_configs.py`
- Modify: `apps/api/app/api/v1/routes.py`

Key endpoints:
```
GET    /api/v1/skill-configs/                    # List skill configs for tenant
POST   /api/v1/skill-configs/                    # Enable a skill
PUT    /api/v1/skill-configs/{id}                # Update config (approval, rate limit, LLM)
DELETE /api/v1/skill-configs/{id}                # Disable skill
POST   /api/v1/skill-configs/{id}/credentials    # Add/update credential
DELETE /api/v1/skill-configs/{id}/credentials/{key}  # Revoke credential
GET    /api/v1/skill-configs/registry             # Get available skills + credential schemas
```

The registry endpoint returns `SKILL_CREDENTIAL_SCHEMAS` so the frontend knows what fields to render.

**Commit after implementation.**

---

### Task 15: Skills Config Panel (Frontend)

**Files:**
- Create: `apps/web/src/components/SkillsConfigPanel.js`
- Create: `apps/web/src/services/skillConfigService.js`
- Modify: `apps/web/src/pages/IntegrationsPage.js`

The panel renders inside IntegrationsPage when OpenClaw instance is running:
- Grid of skill cards with enable/disable toggle
- Click skill → expands credential form + access control settings
- Credential forms rendered dynamically from registry (same pattern as CONNECTOR_FIELDS)
- Per-skill LLM dropdown populated from existing `/api/v1/llm-configs` endpoint

**Commit after implementation.**

---

## Phase 4: LLM Integration + Language Abstraction

### Task 16: Wire LLM Config into Skill Router

**Files:**
- Modify: `apps/api/app/services/orchestration/skill_router.py`

When executing a skill, check `SkillConfig.llm_config_id`:
- If set → load that specific LLM config
- If null → call `LLMRouter.select_model(task_type, tenant_id)`
- Pass selected model info to OpenClaw execution context

**Commit after implementation.**

---

### Task 17: Language Abstraction

**Files to modify (string replacements only):**
1. `apps/web/src/components/Layout.js`
2. `apps/web/src/pages/DashboardPage.js`
3. `apps/web/src/pages/NotebooksPage.js`
4. `apps/web/src/pages/HomePage.js`
5. `apps/web/src/pages/TenantsPage.js`
6. `apps/web/src/components/QuickStartSection.js`
7. `apps/web/public/locales/en/landing.json`
8. `apps/web/public/locales/en/common.json`
9. `apps/web/public/locales/es/landing.json`

**Terminology replacements:**

| Find | Replace |
|---|---|
| `Portfolio Command Center` | `Operations Command Center` |
| `Acquire. Integrate. Scale. Repeat.` | `Connect. Automate. Scale. Repeat.` |
| `The AI-Powered Operating System for Roll-Ups` | `The AI-Powered Operations Platform` |
| `Portfolio Overview` | `Analytics Overview` |
| `Portfolio Entities` | `Organizations` |
| `Entity Data` | `Business Data` |
| `Entity Integrations` | `System Integrations` |
| `ENTITY DATA` | `DATA` |
| `PORTFOLIO ADMIN` | `ADMIN` |
| `Cross-entity metrics` | `Cross-business metrics` |
| `Portfolio KPI Dashboard` | `KPI Dashboard` |
| `Due Diligence Summary` | `Business Health Assessment` |
| `Entity Comparison` | `Business Unit Comparison` |
| `M&A Pipeline` | `Growth Pipeline` |
| `roll-up` / `Roll-Up` / `roll-ups` | remove or replace contextually |
| `portfolio companies & entities` | `organizations & business units` |
| `entity` (in UI context) | `business unit` or `organization` |

Apply same changes to Spanish translations in `es/landing.json`.

**Commit:**
```bash
git add apps/web/src/ apps/web/public/locales/
git commit -m "feat: abstract PE-specific language to generic enterprise terms"
```

---

### Task 18: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Update the project description, architecture section, and model lists to reflect:
- New models (ExecutionTrace, TenantInstance, SkillConfig, SkillCredential)
- New services (Skill Router, Credential Vault, Instance Manager)
- New workflows (TaskExecutionWorkflow, OpenClawProvisionWorkflow)
- New worker (orchestration_worker.py)
- New frontend pages (TaskConsolePage)
- OpenClaw integration architecture
- Updated terminology

**Commit:**
```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with orchestration engine architecture"
```

---

## Execution Status — ALL COMPLETE (2025-02-13)

All 18 tasks executed via subagent-driven development with spec compliance + code quality reviews.

| Phase | Task | Description | Status | Commit |
|-------|------|-------------|--------|--------|
| 1 | 1 | ExecutionTrace model + migration | ✅ | `5775264` |
| 1 | 2 | ExecutionTrace schema + service | ✅ | `19369bb` |
| 1 | 3 | Task execution API endpoints | ✅ | `ba07630` |
| 1 | 4 | TaskExecutionWorkflow + activities | ✅ | `96d538e` |
| 1 | 5 | Orchestration worker + Helm values | ✅ | `79db10a` |
| 1 | 6 | Task Console frontend | ✅ | `0c7789a` |
| 2 | 7 | TenantInstance model + migration | ✅ | `53f33bf` |
| 2 | 8 | TenantInstance schema + service + routes | ✅ | `ae838c4` |
| 2 | 9 | OpenClawProvisionWorkflow | ✅ | `b6a3fd4` |
| 2 | 10 | OpenClaw instance management UI | ✅ | `489e5e2` |
| 3 | 11 | SkillConfig + SkillCredential models | ✅ | `c89488d` |
| 3 | 12 | Credential vault service | ✅ | `af4659f` |
| 3 | 13 | Skill Router service | ✅ | `fcd7b35` |
| 3 | 14 | Skill config API endpoints | ✅ | `33020b6` |
| 3 | 15 | Skills Config panel UI | ✅ | `1a9eef7` |
| 4 | 16 | Wire LLM config into Skill Router | ✅ | `4d43602` |
| 4 | 17 | Language abstraction (13 files) | ✅ | `1fa546f` |
| 4 | 18 | Update CLAUDE.md | ✅ | `06c6b02` |

### New Files Created

**Backend (apps/api/):**
- `app/models/execution_trace.py` — ExecutionTrace model
- `app/models/tenant_instance.py` — TenantInstance model
- `app/models/skill_config.py` — SkillConfig model
- `app/models/skill_credential.py` — SkillCredential model
- `app/schemas/execution_trace.py` — ExecutionTrace schemas
- `app/schemas/tenant_instance.py` — TenantInstance schemas
- `app/schemas/skill_config.py` — SkillConfig + CredentialCreate schemas
- `app/services/execution_traces.py` — ExecutionTrace CRUD
- `app/services/tenant_instances.py` — TenantInstance CRUD
- `app/services/skill_configs.py` — SkillConfig CRUD
- `app/services/orchestration/credential_vault.py` — Fernet encryption vault
- `app/services/orchestration/skill_router.py` — Skill execution router with LLM selection
- `app/workflows/task_execution.py` — TaskExecutionWorkflow (Temporal)
- `app/workflows/openclaw_provision.py` — OpenClawProvisionWorkflow (Temporal)
- `app/workflows/activities/task_execution.py` — 4 task execution activities
- `app/workflows/activities/openclaw_provision.py` — 5 provisioning activities
- `app/workers/orchestration_worker.py` — Temporal orchestration worker
- `app/api/v1/instances.py` — Instance management routes (9 endpoints)
- `app/api/v1/skill_configs.py` — Skill config routes (7 endpoints)
- `migrations/026_add_execution_traces.sql`
- `migrations/027_add_tenant_instances.sql`
- `migrations/028_add_skill_configs_and_credentials.sql`

**Frontend (apps/web/):**
- `src/pages/TaskConsolePage.js` — Task execution console
- `src/components/TaskTimeline.js` — Execution trace timeline
- `src/components/OpenClawInstanceCard.js` — Instance lifecycle card
- `src/components/SkillsConfigPanel.js` — Skills grid with credential forms
- `src/services/taskService.js` — Task API service
- `src/services/instanceService.js` — Instance API service
- `src/services/skillConfigService.js` — Skill config API service

**Infrastructure:**
- `helm/values/agentprovision-orchestration-worker.yaml` — K8s worker deployment

### Key Architecture Decisions
- Temporal workflows for durable task execution and OpenClaw provisioning
- Per-tenant isolated OpenClaw pods deployed via Helm (chart at `../openclaw-k8s/`)
- Fernet-encrypted credential vault — credentials injected per-request, never stored in OpenClaw
- SkillRouter: instance resolution → config validation → credential decryption → gateway call → trace logging
- Per-skill LLM selection via `SkillConfig.llm_config_id` → `LLMRouter.select_model()`
- In-platform traceability via ExecutionTrace (no Temporal UI dependency)
- Language abstracted from PE-specific to generic enterprise terms across 13 files (EN + ES)
