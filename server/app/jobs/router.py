"""Inspect or retry durable work without exposing provider responses."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.jobs.service import WorkRead, get_work, retry_work

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{job_id}", response_model=WorkRead)
def get_job(job_id: UUID, db: Db):
    return get_work(db, job_id)


@router.post("/{job_id}/retry", response_model=WorkRead)
def retry_job(job_id: UUID, db: Db):
    return retry_work(db, job_id)
