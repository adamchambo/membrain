"""Reversible bank maintenance; explanations are edited through revisions."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.captures.models import Conversation
from app.database import get_db
from app.errors import NotFound
from app.knowledge.models import Concept, ConceptRelationship, Resource
from app.knowledge.schemas import ConceptDetail, ResourceDetail, ResourceRead
from app.knowledge.management_schemas import ArchivedRelationshipRead, ConversationPage, ResourcePage
from app.knowledge.service import get_concept, get_resource
from app.pagination import before_cursor, encode_cursor

router = APIRouter(prefix="/api/v1", tags=["bank management"])
Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]


class ConceptPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    archived: bool | None = None


def nullable_patch(schema: dict) -> None:
    """Keep null encoding metadata on the value branch for OpenAPI generators."""
    schema["x-null-encodable"] = True
    for branch in schema.get("anyOf", []):
        if branch.get("type") != "null":
            branch["x-null-encodable"] = True


class ResourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=500, json_schema_extra=nullable_patch)
    note: str | None = Field(default=None, max_length=20000, json_schema_extra=nullable_patch)
    archived: bool | None = None


class ArchivePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: bool


@router.patch("/relationships/{relationship_id}", response_model=ArchivedRelationshipRead)
def archive_relationship(relationship_id: UUID, data: ArchivePatch, db: Db):
    with db.begin():
        item = db.scalar(select(ConceptRelationship).where(ConceptRelationship.id == relationship_id).with_for_update())
        if not item:
            raise NotFound("Relationship not found")
        item.archived_at = (item.archived_at or datetime.now(timezone.utc)) if data.archived else None
        return {"id": item.id, "archived_at": item.archived_at}


def page(db, model, cursor, limit, include_archived=True):
    query = select(model)
    if not include_archived:
        query = query.where(model.archived_at.is_(None))
    if cursor:
        query = query.where(before_cursor(model.created_at, model.id, cursor))
    rows = db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)).all()
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None


@router.patch("/concepts/{concept_id}", response_model=ConceptDetail)
def patch_concept(concept_id: UUID, data: ConceptPatch, db: Db):
    with db.begin():
        item = db.scalar(select(Concept).where(Concept.id == concept_id).with_for_update())
        if item is None:
            raise NotFound("Concept not found")
        if data.title is not None:
            item.title = data.title
        if data.archived is not None:
            item.archived_at = (item.archived_at or datetime.now(timezone.utc)) if data.archived else None
        db.flush()
        return get_concept(db, concept_id)


@router.patch("/resources/{resource_id}", response_model=ResourceDetail)
def patch_resource(resource_id: UUID, data: ResourcePatch, db: Db):
    with db.begin():
        item = db.scalar(select(Resource).where(Resource.id == resource_id).with_for_update())
        if item is None:
            raise NotFound("Resource not found")
        for field in ("title", "note"):
            if field in data.model_fields_set:
                setattr(item, field, getattr(data, field))
        if data.archived is not None:
            item.archived_at = (item.archived_at or datetime.now(timezone.utc)) if data.archived else None
        db.flush()
        return get_resource(db, resource_id)


@router.get("/resources", response_model=ResourcePage)
def list_resources(db: Db, cursor: str | None = None, limit: Limit = 25, include_archived: bool = False):
    rows, following = page(db, Resource, cursor, limit, include_archived)
    return {"items": [ResourceRead.model_validate(row) for row in rows], "next_cursor": following}


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(db: Db, cursor: str | None = None, limit: Limit = 25):
    rows, following = page(db, Conversation, cursor, limit)
    return {"items": [{"id": row.id, "title": row.title, "created_at": row.created_at} for row in rows], "next_cursor": following}
