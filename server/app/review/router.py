"""Cue-card sessions, persisted prompts, and durable answer feedback."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.review import service
from app.review.schemas import AttemptCreate, AttemptRead, QuestionRead, SessionCreate, SessionRead

router = APIRouter(prefix="/api/v1", tags=["review"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/review-sessions", response_model=SessionRead, status_code=201)
def create_session(data: SessionCreate, db: Db):
    return service.create_session(db, data)


@router.post("/review-sessions/{session_id}/next", response_model=QuestionRead)
def next_question(session_id: UUID, db: Db):
    return service.next_question(db, session_id)


@router.post("/review-sessions/{session_id}/attempts", response_model=AttemptRead, status_code=201)
def record_attempt(session_id: UUID, data: AttemptCreate, db: Db):
    return service.record_attempt(db, session_id, data)


@router.get("/review-attempts/{attempt_id}", response_model=AttemptRead)
def get_attempt(attempt_id: UUID, db: Db):
    return service.get_attempt(db, attempt_id)


@router.post("/review-sessions/{session_id}/finish", status_code=204)
def finish_session(session_id: UUID, db: Db):
    service.finish_session(db, session_id)
