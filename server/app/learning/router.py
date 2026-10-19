from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.learning import service
from app.learning.schemas import ArtifactRead, Decision, DecisionRead, TaskCreate, TaskReceipt

router = APIRouter(prefix="/api/v1", tags=["learning"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/learning-tasks", status_code=202, response_model=TaskReceipt)
def create_task(data: TaskCreate, db: Db):
    return service.create(db, data)


@router.get("/learning-artifacts/{artifact_id}", response_model=ArtifactRead)
def artifact_detail(artifact_id: UUID, db: Db):
    return service.detail(db, artifact_id)


@router.post("/learning-suggestions/{suggestion_id}/decision", response_model=DecisionRead)
def decide_suggestion(suggestion_id: UUID, data: Decision, db: Db):
    """A chat client submits the user's conversational decision here."""
    return service.decide(db, suggestion_id, data)
