"""Response shapes for reversible bank maintenance and browsing."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from app.knowledge.schemas import ResourceRead


class ArchivedRelationshipRead(BaseModel):
    id: UUID
    archived_at: datetime | None


class ResourcePage(BaseModel):
    items: list[ResourceRead]
    next_cursor: str | None


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None
