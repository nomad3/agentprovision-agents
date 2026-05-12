from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, model_validator


class ChatSessionBase(BaseModel):
    title: Optional[str] = None


class ChatSessionCreate(ChatSessionBase):
    dataset_id: Optional[uuid.UUID] = None
    dataset_group_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None


class ChatSession(ChatSessionBase):
    id: uuid.UUID
    dataset_id: uuid.UUID | None = None
    dataset_group_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    source: str | None = "native"
    external_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageBase(BaseModel):
    content: str


class ChatMessageCreate(ChatMessageBase):
    pass


class ChatMessage(ChatMessageBase):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    context: dict | None = None
    emotion: str | None = None
    created_at: datetime
    # ``tokens_used`` is already on the ORM model (chat_messages.tokens_used,
    # Integer NULL) and populated by the code-worker callback after each
    # CLI dispatch. Surfacing it here lets `ap session messages` and the
    # web ChatPage show per-message token cost without a schema change.
    # NULL means "not measured" (older messages, agents that don't emit a
    # usage struct) — callers must render the absence as `—`, not 0.
    tokens_used: int | None = None

    @model_validator(mode="after")
    def extract_emotion_from_context(self):
        if self.emotion is None and self.context and "emotion" in self.context:
            self.emotion = self.context["emotion"]
        return self

    class Config:
        from_attributes = True


class ChatTurn(BaseModel):
    user_message: ChatMessage
    assistant_message: ChatMessage
