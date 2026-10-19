"""Search results distinguish confirmed links from semantic candidates."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.knowledge.schemas import RelationshipRead


class SearchHit(BaseModel):
    id: UUID
    type: Literal["concept", "resource"]
    title: str
    match_reason: Literal["title", "explanation", "resource_title", "resource_note", "resource_uri", "semantic"]
    match_source: Literal["text", "semantic", "hybrid"] = "text"
    revision_id: UUID | None = None
    similarity: float | None = None


class SearchResult(BaseModel):
    items: list[SearchHit]
    mode: Literal["text", "semantic", "hybrid"] = "text"
    profile_key: str | None = None
    pending_explanations: int = 0


class RelatedResult(BaseModel):
    confirmed: list[RelationshipRead]
    semantic_candidates: list[SearchHit] = Field(default_factory=list)
    semantic_available: bool = False
    embedding_status: Literal["ready", "pending", "not_configured"] = "not_configured"
    profile_key: str | None = None
