"""Conversation turn routes: the primary way clients talk to Membrain."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.conversation import service
from app.conversation.schemas import TurnCreate, TurnPage, TurnRead
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["conversation"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/turns", response_model=TurnRead, status_code=202)
def submit_turn(data: TurnCreate, db: Db):
    """Save the message now; the worker interprets it, acts and writes the reply."""
    return service.submit(db, data)


@router.get("/turns/{turn_id}", response_model=TurnRead)
def get_turn(turn_id: UUID, db: Db):
    """Poll progress and the reply; progress is persisted, so reconnecting replays it."""
    return service.get(db, turn_id)


@router.post("/turns/{turn_id}/retry", response_model=TurnRead)
def retry_turn(turn_id: UUID, db: Db):
    return service.retry(db, turn_id)


@router.get("/conversations/{conversation_id}/turns", response_model=TurnPage)
def list_turns(conversation_id: UUID, db: Db, before: int | None = None,
               limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.history(db, conversation_id, before, limit)
