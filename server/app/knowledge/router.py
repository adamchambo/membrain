"""Concept, revision, resource, and relationship routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.jobs.service import WorkRead
from app.knowledge import service
from app.knowledge.schemas import (
    ConceptDetail, ConceptPage, RelationshipCreate, RelationshipPage, RelationshipRead,
    ResourceCreate, ResourceDetail, ResourceLink, ResourceRead, RevisionCreate, RevisionPage, RevisionRead,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/concepts", response_model=ConceptPage)
def list_concepts(db: Db, cursor: str | None = None, limit: Limit = 25, include_archived: bool = False):
    items, next_cursor = service.list_concepts(db, cursor, limit, include_archived)
    return ConceptPage(items=items, next_cursor=next_cursor)


@router.get("/concepts/{concept_id}", response_model=ConceptDetail)
def get_concept(concept_id: UUID, db: Db):
    return service.get_concept(db, concept_id)


@router.post("/concepts/{concept_id}/embedding", response_model=WorkRead, status_code=202)
def queue_embedding(concept_id: UUID, db: Db):
    """Queue the current explanation under the active embedding profile."""
    return service.queue_current_embedding(db, concept_id)


@router.get("/concepts/{concept_id}/revisions", response_model=RevisionPage)
def list_revisions(concept_id: UUID, db: Db, cursor: str | None = None, limit: Limit = 25):
    items, next_cursor = service.list_revisions(db, concept_id, cursor, limit)
    return RevisionPage(items=items, next_cursor=next_cursor)


@router.post("/concepts/{concept_id}/revisions", response_model=RevisionRead, status_code=201)
def add_revision(concept_id: UUID, data: RevisionCreate, db: Db):
    return service.add_revision(db, concept_id, data)


@router.post("/resources", response_model=ResourceRead, status_code=201)
def create_resource(data: ResourceCreate, db: Db):
    return service.create_resource(db, data)


@router.get("/resources/{resource_id}", response_model=ResourceDetail)
def get_resource(resource_id: UUID, db: Db):
    return service.get_resource(db, resource_id)


@router.post("/concepts/{concept_id}/resources", status_code=204)
def attach_resource(concept_id: UUID, data: ResourceLink, db: Db):
    service.attach_resource(db, concept_id, data.resource_id)
    return Response(status_code=204)


@router.delete("/concepts/{concept_id}/resources/{resource_id}", status_code=204)
def detach_resource(concept_id: UUID, resource_id: UUID, db: Db):
    service.detach_resource(db, concept_id, resource_id)
    return Response(status_code=204)


@router.get("/concepts/{concept_id}/relationships", response_model=RelationshipPage)
def list_relationships(concept_id: UUID, db: Db, cursor: str | None = None, limit: Limit = 25):
    items, next_cursor = service.list_relationships(db, concept_id, cursor, limit)
    return RelationshipPage(items=items, next_cursor=next_cursor)


@router.post("/concepts/{concept_id}/relationships", response_model=RelationshipRead, status_code=201)
def add_relationship(concept_id: UUID, data: RelationshipCreate, db: Db):
    return service.add_relationship(db, concept_id, data)
