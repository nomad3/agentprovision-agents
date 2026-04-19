"""Analytics service for dashboard metrics and insights."""
from __future__ import annotations

from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
import uuid

from app.models.agent import Agent
from app.models.data_source import DataSource
from app.models.data_pipeline import DataPipeline
from app.models.notebook import Notebook
from app.models.dataset import Dataset
from app.models.deployment import Deployment
from app.models.chat import ChatSession, ChatMessage
from app.models.tool import Tool
from app.models.vector_store import VectorStore
from app.schemas.analytics import AnalyticsSummary


def get_analytics_summary(db: Session, tenant_id: uuid.UUID) -> AnalyticsSummary:
    """Get basic analytics summary for a tenant."""
    total_agents = db.query(Agent).filter(Agent.tenant_id == tenant_id).count()
    total_data_sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id).count()
    total_data_pipelines = db.query(DataPipeline).filter(DataPipeline.tenant_id == tenant_id).count()
    total_notebooks = db.query(Notebook).filter(Notebook.tenant_id == tenant_id).count()

    return AnalyticsSummary(
        total_agents=total_agents,
        total_data_sources=total_data_sources,
        total_data_pipelines=total_data_pipelines,
        total_notebooks=total_notebooks,
    )


def get_dashboard_stats(db: Session, tenant_id: uuid.UUID) -> Dict[str, Any]:
    """
    Get comprehensive dashboard statistics.

    Returns real data from the database including:
    - Platform overview metrics
    - Agent and deployment stats
    - Data platform health
    - Recent activity
    """
    # Core metrics
    total_agents = db.query(Agent).filter(Agent.tenant_id == tenant_id).count()
    total_deployments = db.query(Deployment).filter(Deployment.tenant_id == tenant_id).count()
    total_datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id).count()
    total_chat_sessions = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()
    total_data_sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id).count()
    total_pipelines = db.query(DataPipeline).filter(DataPipeline.tenant_id == tenant_id).count()
    total_vector_stores = db.query(VectorStore).filter(VectorStore.tenant_id == tenant_id).count()
    total_tools = db.query(Tool).filter(Tool.tenant_id == tenant_id).count()

    # Chat activity metrics
    total_messages = db.query(ChatMessage).join(
        ChatSession, ChatMessage.session_id == ChatSession.id
    ).filter(ChatSession.tenant_id == tenant_id).count()

    user_messages = db.query(ChatMessage).join(
        ChatSession, ChatMessage.session_id == ChatSession.id
    ).filter(
        ChatSession.tenant_id == tenant_id,
        ChatMessage.role == "user"
    ).count()

    # Dataset analytics
    dataset_rows_total = db.query(func.sum(Dataset.row_count)).filter(
        Dataset.tenant_id == tenant_id
    ).scalar() or 0

    # Recent activity - last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)

    recent_chat_sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.created_at >= week_ago
    ).count()

    recent_messages = db.query(ChatMessage).join(
        ChatSession, ChatMessage.session_id == ChatSession.id
    ).filter(
        ChatSession.tenant_id == tenant_id,
        ChatMessage.created_at >= week_ago
    ).count()

    # Get agent list with deployment counts
    agents_with_deployments = db.query(
        Agent.name,
        func.count(Deployment.id).label('deployment_count')
    ).outerjoin(
        Deployment, Agent.id == Deployment.agent_id
    ).filter(
        Agent.tenant_id == tenant_id
    ).group_by(Agent.id, Agent.name).all()

    # Get dataset list with details
    datasets = db.query(Dataset).filter(
        Dataset.tenant_id == tenant_id
    ).order_by(desc(Dataset.created_at)).limit(10).all()

    dataset_list = [{
        "id": str(ds.id),
        "name": ds.name,
        "rows": ds.row_count or 0,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
    } for ds in datasets]

    # Get recent chat sessions
    recent_sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id
    ).order_by(desc(ChatSession.created_at)).limit(5).all()

    session_list = [{
        "id": str(session.id),
        "title": session.title or "Untitled Chat",
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "message_count": db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id
        ).count()
    } for session in recent_sessions]

    return {
        "overview": {
            "total_agents": total_agents,
            "total_deployments": total_deployments,
            "total_datasets": total_datasets,
            "total_chat_sessions": total_chat_sessions,
            "total_data_sources": total_data_sources,
            "total_pipelines": total_pipelines,
            "total_vector_stores": total_vector_stores,
            "total_tools": total_tools,
        },
        "activity": {
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": total_messages - user_messages,
            "recent_chat_sessions_7d": recent_chat_sessions,
            "recent_messages_7d": recent_messages,
            "dataset_rows_total": int(dataset_rows_total),
        },
        "agents": [{
            "name": agent.name,
            "deployment_count": agent.deployment_count
        } for agent in agents_with_deployments],
        "datasets": dataset_list,
        "recent_sessions": session_list,
    }
