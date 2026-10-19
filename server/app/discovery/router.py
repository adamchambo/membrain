"""Text discovery and dated learning activity."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.captures.models import Capture
from app.database import get_db
from app.knowledge.models import CaptureConcept, Concept, ConceptRelationship, ConceptResource, ExplanationRevision, Resource
from app.discovery import service
from app.discovery.schemas import RelatedResult, SearchResult
from app.knowledge.service import require_concept
from app.pagination import before_cursor, encode_cursor
from app.review.models import ReviewAttempt, ReviewAttemptConcept

router = APIRouter(prefix="/api/v1", tags=["discovery"])
Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/search", response_model=SearchResult)
def search(db: Db, q: Annotated[str, Query(min_length=1)], mode: Literal["text", "semantic", "hybrid"] = "text",
           limit: Limit = 25):
    return service.search(db, q, mode, limit)


@router.get("/concepts/{concept_id}/related", response_model=RelatedResult)
def related(concept_id: UUID, db: Db, limit: Limit = 25):
    return service.related(db, concept_id, limit)


class Activity(BaseModel):
    id: UUID
    type: Literal["capture", "explanation", "resource", "relationship", "review_attempt"]
    occurred_at: datetime
    concept_id: UUID | None = None


class ActivityPage(BaseModel):
    items: list[Activity]
    next_cursor: str | None


def activity_page(db: Session, cursor: str | None, limit: int, concept_id: UUID | None,
                  include_resources: bool) -> ActivityPage:
    if concept_id:
        require_concept(db, concept_id)
    events = []
    def page(query, timestamp_column, id_column):
        if cursor:
            query = query.where(before_cursor(timestamp_column, id_column, cursor))
        return db.scalars(query.order_by(timestamp_column.desc(), id_column.desc()).limit(limit + 1)).all()

    captures = select(Capture)
    if concept_id:
        captures = captures.where(Capture.id.in_(select(CaptureConcept.capture_id).where(CaptureConcept.concept_id == concept_id)))
    events += [Activity(id=x.id, type="capture", occurred_at=x.created_at, concept_id=concept_id)
               for x in page(captures, Capture.created_at, Capture.id)]
    events += [Activity(id=x.id, type="explanation", occurred_at=x.created_at, concept_id=x.concept_id)
               for x in page(select(ExplanationRevision).where(
                   ExplanationRevision.concept_id == concept_id if concept_id else True),
                   ExplanationRevision.created_at, ExplanationRevision.id)]
    if include_resources:
        resources = select(Resource)
        if concept_id:
            resources = resources.where(Resource.id.in_(select(ConceptResource.resource_id).where(ConceptResource.concept_id == concept_id)))
        events += [Activity(id=x.id, type="resource", occurred_at=x.created_at, concept_id=concept_id)
                   for x in page(resources, Resource.created_at, Resource.id)]
    events += [Activity(id=x.id, type="relationship", occurred_at=x.confirmed_at, concept_id=x.source_concept_id)
               for x in page(select(ConceptRelationship).where(
                   ((ConceptRelationship.source_concept_id == concept_id) |
                    (ConceptRelationship.target_concept_id == concept_id)) if concept_id else True),
                    ConceptRelationship.confirmed_at, ConceptRelationship.id)]
    attempts = select(ReviewAttempt)
    if concept_id:
        attempts = attempts.where(ReviewAttempt.id.in_(select(ReviewAttemptConcept.review_attempt_id).where(ReviewAttemptConcept.concept_id == concept_id)))
    events += [Activity(id=x.id, type="review_attempt", occurred_at=x.answered_at, concept_id=concept_id)
               for x in page(attempts, ReviewAttempt.answered_at, ReviewAttempt.id)]
    events.sort(key=lambda x: (x.occurred_at, x.id), reverse=True)
    next_cursor = encode_cursor(events[limit - 1].occurred_at, events[limit - 1].id) if len(events) > limit else None
    return ActivityPage(items=events[:limit], next_cursor=next_cursor)


@router.get("/recents", response_model=ActivityPage)
def recents(db: Db, cursor: str | None = None, limit: Limit = 25):
    return activity_page(db, cursor, limit, None, True)


@router.get("/timeline", response_model=ActivityPage)
def timeline(db: Db, cursor: str | None = None, limit: Limit = 25, concept_id: UUID | None = None):
    return activity_page(db, cursor, limit, concept_id, True)
