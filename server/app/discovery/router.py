"""Text discovery and dated learning activity."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.captures.models import Capture
from app.database import get_db
from app.errors import Unavailable
from app.knowledge.models import Concept, ConceptRelationship, ExplanationRevision, Resource
from app.knowledge.schemas import RelationshipRead
from app.knowledge.service import require_concept
from app.pagination import before_cursor, encode_cursor
from app.review.models import ReviewAttempt

router = APIRouter(prefix="/api/v1", tags=["discovery"])
Db = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]


class SearchHit(BaseModel):
    id: UUID
    type: Literal["concept", "resource"]
    title: str
    match_reason: Literal["title", "explanation", "resource_title", "resource_note", "resource_uri"]
    match_source: Literal["text"] = "text"


class SearchResult(BaseModel):
    items: list[SearchHit]
    mode: Literal["text"] = "text"


@router.get("/search", response_model=SearchResult)
def search(db: Db, q: Annotated[str, Query(min_length=1)], mode: Literal["text", "semantic", "hybrid"] = "text",
           limit: Limit = 25):
    if mode != "text":
        raise Unavailable("Semantic search requires an embedding profile and generation service")
    term = q.strip()
    if not term:
        return SearchResult(items=[])
    escaped = term.replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    hits = []
    explanation_match = select(ExplanationRevision.id).where(
        ExplanationRevision.concept_id == Concept.id,
        ExplanationRevision.body.ilike(pattern, escape="\\"),
    ).exists()
    concepts = db.scalars(select(Concept).where(
        Concept.archived_at.is_(None),
        or_(Concept.title.ilike(pattern, escape="\\"), explanation_match),
    ).order_by(case((Concept.title.ilike(pattern, escape="\\"), 0), else_=2),
               Concept.created_at.desc()).limit(limit)).all()
    for concept in concepts:
        reason = None
        if term.casefold() in concept.title.casefold():
            reason = "title"
        else:
            reason = "explanation"
        if reason:
            hits.append(SearchHit(id=concept.id, type="concept", title=concept.title, match_reason=reason))
    resources = db.scalars(select(Resource).where(or_(
        Resource.title.ilike(pattern, escape="\\"), Resource.note.ilike(pattern, escape="\\"),
        Resource.uri.ilike(pattern, escape="\\"),
    )).order_by(case((Resource.title.ilike(pattern, escape="\\"), 1),
                     (Resource.note.ilike(pattern, escape="\\"), 3), else_=4),
                Resource.created_at.desc()).limit(limit)).all()
    for resource in resources:
        reason = ("resource_title" if resource.title and term.casefold() in resource.title.casefold() else
                  "resource_note" if resource.note and term.casefold() in resource.note.casefold() else
                  "resource_uri" if term.casefold() in resource.uri.casefold() else None)
        if reason:
            hits.append(SearchHit(id=resource.id, type="resource", title=resource.title or resource.uri, match_reason=reason))
    priority = {"title": 0, "resource_title": 1, "explanation": 2, "resource_note": 3, "resource_uri": 4}
    return SearchResult(items=sorted(hits, key=lambda hit: (priority[hit.match_reason], hit.title.casefold()))[:limit])


class RelatedResult(BaseModel):
    confirmed: list[RelationshipRead]
    semantic_candidates: list[dict] = []
    semantic_available: bool = False


@router.get("/concepts/{concept_id}/related", response_model=RelatedResult)
def related(concept_id: UUID, db: Db, limit: Limit = 25):
    require_concept(db, concept_id)
    rows = db.scalars(select(ConceptRelationship).where(
        (ConceptRelationship.source_concept_id == concept_id) | (ConceptRelationship.target_concept_id == concept_id)
    ).order_by(ConceptRelationship.confirmed_at.desc()).limit(limit)).all()
    return RelatedResult(confirmed=rows)


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

    if concept_id is None:
        events += [Activity(id=x.id, type="capture", occurred_at=x.created_at)
                   for x in page(select(Capture), Capture.created_at, Capture.id)]
    events += [Activity(id=x.id, type="explanation", occurred_at=x.created_at, concept_id=x.concept_id)
               for x in page(select(ExplanationRevision).where(
                   ExplanationRevision.concept_id == concept_id if concept_id else True),
                   ExplanationRevision.created_at, ExplanationRevision.id)]
    if concept_id is None and include_resources:
        events += [Activity(id=x.id, type="resource", occurred_at=x.created_at)
                   for x in page(select(Resource), Resource.created_at, Resource.id)]
    events += [Activity(id=x.id, type="relationship", occurred_at=x.confirmed_at, concept_id=x.source_concept_id)
               for x in page(select(ConceptRelationship).where(
                   ((ConceptRelationship.source_concept_id == concept_id) |
                    (ConceptRelationship.target_concept_id == concept_id)) if concept_id else True),
                    ConceptRelationship.confirmed_at, ConceptRelationship.id)]
    if concept_id is None:
        events += [Activity(id=x.id, type="review_attempt", occurred_at=x.answered_at)
                   for x in page(select(ReviewAttempt), ReviewAttempt.answered_at, ReviewAttempt.id)]
    events.sort(key=lambda x: (x.occurred_at, x.id), reverse=True)
    next_cursor = encode_cursor(events[limit - 1].occurred_at, events[limit - 1].id) if len(events) > limit else None
    return ActivityPage(items=events[:limit], next_cursor=next_cursor)


@router.get("/recents", response_model=ActivityPage)
def recents(db: Db, cursor: str | None = None, limit: Limit = 25):
    return activity_page(db, cursor, limit, None, True)


@router.get("/timeline", response_model=ActivityPage)
def timeline(db: Db, cursor: str | None = None, limit: Limit = 25, concept_id: UUID | None = None):
    return activity_page(db, cursor, limit, concept_id, True)
