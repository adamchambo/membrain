"""Queue writes share the transaction that saves the source record."""

from datetime import datetime, timezone
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.embeddings import configured_profile, persist_profile
from app.errors import Conflict, NotConfigured, NotFound
from app.jobs.models import WorkItem


class WorkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: Literal["capture", "embedding", "review_feedback"]
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    attempts: int
    last_error: str | None
    profile_key: str | None
    available_at: datetime


def enqueue_capture(db: Session, capture_id: UUID) -> UUID:
    return enqueue(db, dedup_key=f"capture:{capture_id}", kind="capture", capture_id=capture_id)


def enqueue_embedding(db: Session, revision_id: UUID) -> UUID:
    try:
        profile = configured_profile()
        persist_profile(db, profile)
        key = profile.key
    except NotConfigured:
        key = None
    return enqueue(db, dedup_key=f"embedding:{revision_id}:{key or 'unconfigured'}", kind="embedding",
                   revision_id=revision_id, profile_key=key)


def enqueue(db: Session, **values) -> UUID:
    statement = insert(WorkItem).values(**values).on_conflict_do_nothing(index_elements=[WorkItem.dedup_key]).returning(WorkItem.id)
    result = db.scalar(statement)
    return result or db.scalar(select(WorkItem.id).where(WorkItem.dedup_key == values["dedup_key"]))


def get_work(db: Session, job_id: UUID) -> WorkItem:
    result = db.get(WorkItem, job_id)
    if result is None:
        raise NotFound("Work record not found")
    return result


def retry_work(db: Session, job_id: UUID) -> WorkItem:
    with db.begin():
        job = db.scalar(select(WorkItem).where(WorkItem.id == job_id).with_for_update())
        if job is None:
            raise NotFound("Work record not found")
        if job.status not in ("failed", "pending"):
            raise Conflict("Only pending or failed work can be retried")
        job.status = "pending"
        job.attempts = 0
        job.available_at = datetime.now(timezone.utc)
        job.last_error = None
    return job
