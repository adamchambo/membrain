"""Knowledge and resource API shapes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Nonblank(BaseModel):
    @field_validator("explanation_text", "uri", "title", "relation_type", check_fields=False)
    @classmethod
    def strip_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value.strip()


class RevisionCreate(Nonblank):
    explanation_text: str = Field(min_length=1)
    capture_id: UUID | None = None


class RevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    concept_id: UUID
    capture_id: UUID | None
    proposal_id: UUID | None
    revision_number: int
    body: str
    origin: Literal["user_written", "ai_formatted_user_input", "user_edited_format", "user_confirmed_suggestion"]
    suggestion_id: UUID | None = None
    created_at: datetime
    retracted_at: datetime | None = None


class RevisionPage(BaseModel):
    items: list[RevisionRead]
    next_cursor: str | None


class ConceptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    archived_at: datetime | None
    latest_revision: RevisionRead | None


class ConceptPage(BaseModel):
    items: list[ConceptSummary]
    next_cursor: str | None


class ResourceCreate(Nonblank):
    kind: Literal["article", "post", "site", "document", "video", "other"]
    uri: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=500)
    note: str | None = None


class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    capture_id: UUID | None
    kind: str
    uri: str
    title: str | None
    note: str | None
    created_at: datetime
    archived_at: datetime | None = None


class ResourceDetail(ResourceRead):
    concept_ids: list[UUID]


class ResourceLink(BaseModel):
    resource_id: UUID


class RelationshipCreate(Nonblank):
    target_concept_id: UUID
    relation_type: Literal["related_to", "prerequisite_of", "part_of", "applies_to"]
    rationale: str | None = None


class RelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_concept_id: UUID
    target_concept_id: UUID
    relation_type: str
    rationale: str | None
    confirmed_at: datetime


class RelationshipPage(BaseModel):
    items: list[RelationshipRead]
    next_cursor: str | None


class ConceptDetail(ConceptSummary):
    resources: list[ResourceRead]
    relationships: list[RelationshipRead]
