from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import Conflict, NotFound
from app.knowledge.models import Concept, ExplanationRevision
from app.learning.models import Subject, SubjectConcept
from app.learning.scopes import resolve_subject
from app.learning.scope_schemas import (SubjectRead, SubjectList, MembershipRead, SubjectScopeRead,
    ReviewHistory, SessionDetail, ReflectionRead)
from app.review.models import ReviewAttempt, ReviewAttemptConcept, ReviewQuestion, ReviewScopeConcept, ReviewSession
from app.review.service import attempt_read

router = APIRouter(prefix="/api/v1", tags=["subjects and reflection"])
Db = Annotated[Session, Depends(get_db)]


class SubjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None


@router.post("/subjects", status_code=201, response_model=SubjectRead)
def create_subject(data: SubjectCreate, db: Db):
    with db.begin():
        if data.parent_id and db.get(Subject, data.parent_id) is None:
            raise NotFound("Parent subject not found")
        item = Subject(**data.model_dump())
        db.add(item)
        db.flush()
        return {"id": item.id, "title": item.title, "parent_id": item.parent_id}


@router.get("/subjects", response_model=SubjectList)
def list_subjects(db: Db, limit: int = Query(default=100, ge=1, le=500)):
    return {"items": [{"id": row.id, "title": row.title, "parent_id": row.parent_id}
        for row in db.scalars(select(Subject).order_by(Subject.title, Subject.id).limit(limit)).all()]}


@router.put("/subjects/{subject_id}/concepts/{concept_id}", response_model=MembershipRead)
def add_membership(subject_id: UUID, concept_id: UUID, db: Db):
    with db.begin():
        if db.get(Subject, subject_id) is None or db.get(Concept, concept_id) is None:
            raise NotFound("Subject or concept not found")
        db.execute(insert(SubjectConcept).values(subject_id=subject_id, concept_id=concept_id).on_conflict_do_nothing())
        return {"subject_id": subject_id, "concept_id": concept_id}


@router.get("/subjects/{subject_id}/scope", response_model=SubjectScopeRead)
def subject_scope(subject_id: UUID, db: Db):
    return {"subject_id": subject_id, "concept_ids": resolve_subject(db, subject_id), "includes_descendants": True}


@router.get("/review-sessions", response_model=ReviewHistory)
def review_history(db: Db, limit: int = Query(default=25, ge=1, le=100)):
    rows = db.scalars(select(ReviewSession).order_by(ReviewSession.started_at.desc(), ReviewSession.id.desc()).limit(limit)).all()
    return {"items": [{"id": row.id, "mode": row.mode, "requested_scope": row.requested_scope,
                       "started_at": row.started_at, "finished_at": row.finished_at} for row in rows]}


@router.get("/review-sessions/{session_id}", response_model=SessionDetail)
def session_detail(session_id: UUID, db: Db):
    item = db.get(ReviewSession, session_id)
    if item is None:
        raise NotFound("Review session not found")
    questions = db.scalars(select(ReviewQuestion).where(ReviewQuestion.review_session_id == session_id)
        .order_by(ReviewQuestion.created_at).limit(200)).all()
    attempts = db.scalars(select(ReviewAttempt).where(ReviewAttempt.review_session_id == session_id)
        .order_by(ReviewAttempt.answered_at).limit(200)).all()
    return {"id": item.id, "mode": item.mode, "finished_at": item.finished_at,
            "questions": [{"id": q.id, "concept_id": q.concept_id, "prompt": q.prompt, "snapshot": q.snapshot} for q in questions],
            "attempts": [attempt_read(db, attempt) for attempt in attempts]}


@router.get("/reflection", response_model=ReflectionRead)
def reflect(db: Db, subject_id: UUID | None = None, since: datetime | None = None, until: datetime | None = None):
    if (since and since.tzinfo is None) or (until and until.tzinfo is None) or (since and until and since > until):
        raise Conflict("Use an ordered interval with timezone-aware timestamps")
    ids = resolve_subject(db, subject_id) if subject_id else list(db.scalars(select(Concept.id).where(Concept.archived_at.is_(None))).all())
    if len(ids) > 2000:
        raise Conflict("Choose a narrower subject")
    revisions = select(ExplanationRevision).where(ExplanationRevision.concept_id.in_(ids))
    attempts = select(ReviewAttempt).join(ReviewAttemptConcept, ReviewAttemptConcept.review_attempt_id == ReviewAttempt.id).where(ReviewAttemptConcept.concept_id.in_(ids))
    if since:
        revisions = revisions.where(ExplanationRevision.created_at >= since)
        attempts = attempts.where(ReviewAttempt.answered_at >= since)
    if until:
        revisions = revisions.where(ExplanationRevision.created_at <= until)
        attempts = attempts.where(ReviewAttempt.answered_at <= until)
    saved = db.scalars(revisions.order_by(ExplanationRevision.created_at.desc()).limit(501)).all()
    answered = db.scalars(attempts.order_by(ReviewAttempt.answered_at.desc()).distinct().limit(501)).all()
    assessed = set(db.scalars(select(ReviewAttemptConcept.concept_id).where(ReviewAttemptConcept.review_attempt_id.in_([a.id for a in answered[:500]]))).all())
    return {"eligible_concept_ids": ids, "reviewed_concept_ids": sorted(assessed.intersection(ids)),
            "unreviewed_concept_ids": sorted(set(ids) - assessed),
            "revisions": [{"id": r.id, "concept_id": r.concept_id, "origin": r.origin, "retracted_at": r.retracted_at} for r in saved[:500]],
            "attempts": [attempt_read(db, a) for a in answered[:500]],
            "truncated": len(saved) > 500 or len(answered) > 500, "mastery": "not_inferred"}
