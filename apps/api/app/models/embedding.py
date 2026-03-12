"""Embedding model — stores vector embeddings for semantic search."""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    content_type = Column(String(50), nullable=False, index=True)
    content_id = Column(String(255), nullable=False)
    embedding = Column(Vector(768), nullable=False)
    text_content = Column(Text, nullable=True)
    task_type = Column(String(50), default="RETRIEVAL_DOCUMENT")
    model = Column(String(100), default="gemini-embedding-2-preview")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
