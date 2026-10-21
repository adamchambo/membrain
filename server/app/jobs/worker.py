"""Run durable work with short claim transactions and fenced result writes.

Start with: python -m app.jobs.worker
"""

import logging
import json
import signal
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.ai.embeddings import Profile, configured_profile, embed, persist_profile
from app.captures.formatter import get_formatter
from app.captures.ingestion import DeferredWork, apply_output, capture_context, query_vector
from app.captures.models import Capture
from app.database import db_engine
from app.errors import AppError, NotConfigured
from app.jobs.models import EmbeddingProfile, WorkItem
from app.knowledge.models import ConceptEmbedding, ExplanationRevision
from app.review.models import ReviewAttempt, ReviewQuestion
from app.review.questions import assess_answer

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def claim(engine: Engine, job_id: UUID | None = None):
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        query = select(WorkItem).where(or_(
            and_(WorkItem.status == "pending", WorkItem.available_at <= now),
            and_(WorkItem.status == "running", WorkItem.lease_until < now)))
        if job_id:
            query = query.where(WorkItem.id == job_id)
        job = db.scalar(query.order_by(WorkItem.available_at, WorkItem.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "failed"
            job.last_error = "Processing stopped after repeated failures; retry when ready"
            return None
        job.status = "running"
        job.attempts += 1
        job.lease_token = uuid4()
        job.lease_until = now + timedelta(seconds=120)
        return job.id, job.lease_token, job.kind


def owned_job(db: Session, job_id: UUID, token: UUID) -> WorkItem | None:
    job = db.scalar(select(WorkItem).where(WorkItem.id == job_id).with_for_update())
    return job if job and job.status == "running" and job.lease_token == token else None


def process_capture(engine: Engine, job_id: UUID, token: UUID, processor=None):
    with Session(engine) as db:
        job = db.get(WorkItem, job_id)
        capture_id = job.capture_id
        capture = db.get(Capture, capture_id)
        raw_text = capture.raw_text if capture.status == "pending" else None
    context = None
    if raw_text is not None:
        # Neither the query embedding nor inference holds a database transaction.
        query = query_vector(engine, raw_text)
        with Session(engine) as db:
            context = capture_context(db, db.get(Capture, capture_id), query)
    if context is not None:
        processor = processor or get_formatter()
        output = processor.process(raw_text, context)
    with Session(engine) as db, db.begin():
        job = owned_job(db, job_id, token)
        if job is None:
            return
        capture = db.scalar(select(Capture).where(Capture.id == job.capture_id).with_for_update())
        if capture.status == "archived":
            job.status = "cancelled"
        elif capture.status == "processed":
            job.status = "succeeded"
        else:
            if context is None:
                raise DeferredWork("Capture changed while processing")
            apply_output(db, capture, output, context, processor.model_key, processor.prompt_version)
            job.status = "succeeded"
        job.lease_token = None
        job.lease_until = None
        job.last_error = None


def process_embedding(engine: Engine, job_id: UUID, token: UUID, embedder=None):
    with Session(engine) as db, db.begin():
        job = owned_job(db, job_id, token)
        if job is None:
            return
        revision = db.get(ExplanationRevision, job.revision_id)
        if revision is None or revision.retracted_at:
            job.status = "cancelled"
            job.lease_token = None
            return
        if job.profile_key is None:
            from app.setup.profiles import initialize_active
            profile = initialize_active(db)
            persist_profile(db, profile)
            job.profile_key = profile.key
        else:
            profile = Profile.model_validate(db.get(EmbeddingProfile, job.profile_key).settings)
        revision_id, body = revision.id, revision.body
    # Neither inference nor the HTTP call holds a database transaction.
    vector = (embedder or embed)(body, profile)
    with Session(engine) as db, db.begin():
        job = owned_job(db, job_id, token)
        if job is None:
            return
        revision = db.scalar(select(ExplanationRevision).where(ExplanationRevision.id == revision_id).with_for_update())
        if revision is None or revision.retracted_at:
            job.status = "cancelled"
        else:
            db.execute(insert(ConceptEmbedding).values(explanation_revision_id=revision_id,
                model_key=profile.key, embedding=vector).on_conflict_do_nothing(
                    index_elements=[ConceptEmbedding.explanation_revision_id, ConceptEmbedding.model_key]))
            job.status = "succeeded"
        job.lease_token = None
        job.lease_until = None
        job.last_error = None


def process_feedback(engine: Engine, job_id: UUID, token: UUID, assessor=None):
    with Session(engine) as db:
        job = db.get(WorkItem, job_id)
        attempt = db.get(ReviewAttempt, job.attempt_id)
        question = db.get(ReviewQuestion, attempt.question_id)
        snapshot, prompt, response = question.snapshot, question.prompt, attempt.response
    feedback = (assessor or assess_answer)(snapshot, prompt, response)
    with Session(engine) as db, db.begin():
        job = owned_job(db, job_id, token)
        if job is None:
            return
        attempt = db.scalar(select(ReviewAttempt).where(ReviewAttempt.id == job.attempt_id).with_for_update())
        attempt.feedback = json.dumps(feedback)
        job.status = "succeeded"
        job.lease_token = None
        job.lease_until = None
        job.last_error = None


def run_one(engine: Engine, *, job_id: UUID | None = None, processor=None, embedder=None, assessor=None, client=None) -> bool:
    """Claim one eligible job; optional task adapters and chat client support isolated testing."""
    claimed = claim(engine, job_id)
    if claimed is None:
        return False
    record_id, token, kind = claimed
    try:
        if kind == "turn":
            from app.conversation.processor import process_turn
            process_turn(engine, record_id, token, client)
        elif kind == "capture":
            process_capture(engine, record_id, token, processor)
        elif kind == "embedding":
            process_embedding(engine, record_id, token, embedder)
        elif kind == "review_feedback":
            process_feedback(engine, record_id, token, assessor)
        elif kind == "profile_migration":
            from app.setup.profiles import populate_migration
            with Session(engine) as db, db.begin():
                job = owned_job(db, record_id, token)
                if job is not None:
                    job.result = populate_migration(db, job.arguments)
                    job.status = "succeeded"
                    job.lease_token = None
                    job.lease_until = None
        else:
            from app.jobs.features import process_feature
            process_feature(engine, record_id, token, kind)
    except Exception as exc:
        with Session(engine) as db, db.begin():
            job = owned_job(db, record_id, token)
            if job is not None:
                deferred = isinstance(exc, (NotConfigured, DeferredWork))
                if deferred:
                    job.attempts -= 1
                job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"
                delay = 60 if isinstance(exc, NotConfigured) else 2 if isinstance(exc, DeferredWork) else min(300, 2 ** job.attempts)
                job.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                job.last_error = exc.message if isinstance(exc, AppError) else "Waiting for previous or updated context" if deferred else "Processing failed; the original input is still saved"
                job.lease_token = None
                job.lease_until = None
        logger.warning("Work %s did not complete (%s)", record_id, type(exc).__name__)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker_id = str(uuid4())
    while not stopped:
        try:
            from app.setup.models import WorkerHeartbeat
            with Session(db_engine()) as db, db.begin():
                db.execute(insert(WorkerHeartbeat).values(id=worker_id, seen_at=datetime.now(timezone.utc))
                    .on_conflict_do_update(index_elements=[WorkerHeartbeat.id], set_={"seen_at": datetime.now(timezone.utc)}))
            if not run_one(db_engine()):
                time.sleep(2)
        except Exception as exc:
            logger.error("Worker temporarily unavailable (%s)", type(exc).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()
