"""Persist questions before answers and save answers before feedback inference."""

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.jobs.models import WorkItem
from app.jobs.service import enqueue
from app.knowledge.models import Concept, ExplanationRevision
from app.knowledge.service import latest_revision
from app.review.models import ReviewAttempt, ReviewAttemptConcept, ReviewQuestion, ReviewScopeConcept, ReviewSession
from app.review.questions import generate_question
from app.review.schemas import AttemptCreate, AttemptRead, SessionCreate, SessionRead


def create_session(db: Session, data: SessionCreate) -> SessionRead:
    with db.begin():
        for concept_id in data.concept_ids:
            concept = db.get(Concept, concept_id)
            if not concept or concept.archived_at or latest_revision(db, concept_id) is None:
                raise Conflict("Review scope must contain active concepts with saved explanations")
        session = ReviewSession(requested_scope=json.dumps([str(x) for x in data.concept_ids]), mode=data.mode)
        db.add(session)
        db.flush()
        for concept_id in data.concept_ids:
            db.add(ReviewScopeConcept(review_session_id=session.id, concept_id=concept_id))
        result = SessionRead(id=session.id, mode=session.mode, concept_ids=data.concept_ids)
    return result


def require_session(db: Session, session_id: UUID, *, lock: bool = False) -> ReviewSession:
    query = select(ReviewSession).where(ReviewSession.id == session_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    session = db.scalar(query)
    if session is None:
        raise NotFound("Review session not found")
    if session.finished_at:
        raise Conflict("Review session is finished")
    return session


def pending_question(db: Session, session_id: UUID):
    return db.scalar(select(ReviewQuestion).join(ExplanationRevision, ExplanationRevision.id == ReviewQuestion.revision_id)
        .where(ExplanationRevision.retracted_at.is_(None), ReviewQuestion.review_session_id == session_id,
        ReviewQuestion.answered_at.is_(None)).order_by(ReviewQuestion.created_at).limit(1))


def next_question(db: Session, session_id: UUID) -> ReviewQuestion:
    with db.begin():
        require_session(db, session_id)
        pending = pending_question(db, session_id)
        if pending:
            return pending
        scope = db.scalars(select(Concept).join(ReviewScopeConcept, ReviewScopeConcept.concept_id == Concept.id)
            .where(ReviewScopeConcept.review_session_id == session_id, Concept.archived_at.is_(None)).order_by(Concept.id)).all()
        choices = [(concept, latest_revision(db, concept.id)) for concept in scope]
        choices = [(c, r) for c, r in choices if r]
        if not choices:
            raise Conflict("No active explanations remain in this review scope")
        count = db.scalar(select(func.count()).select_from(ReviewQuestion).where(ReviewQuestion.review_session_id == session_id)) or 0
        concept, revision = choices[count % len(choices)]
        snapshot = {"concept_id": str(concept.id), "title": concept.title, "revision_id": str(revision.id), "explanation": revision.body}
    prompt, model, version = generate_question(snapshot)
    with db.begin():
        require_session(db, session_id, lock=True)
        pending = pending_question(db, session_id)
        if pending:
            return pending
        revision = db.get(ExplanationRevision, UUID(snapshot["revision_id"]), populate_existing=True)
        if revision is None or revision.retracted_at:
            raise Conflict("The selected explanation was undone; request another question")
        question = ReviewQuestion(review_session_id=session_id, concept_id=UUID(snapshot["concept_id"]),
            revision_id=revision.id, snapshot=snapshot, prompt=prompt, model_key=model, prompt_version=version)
        db.add(question)
        db.flush()
    return question


def attempt_read(db: Session, attempt: ReviewAttempt) -> AttemptRead:
    feedback = None
    if attempt.feedback:
        try:
            feedback = json.loads(attempt.feedback)
        except ValueError:
            feedback = {"feedback": attempt.feedback, "correctness": "not_verified"}
    job_id = db.scalar(select(WorkItem.id).where(WorkItem.attempt_id == attempt.id))
    return AttemptRead(id=attempt.id, review_session_id=attempt.review_session_id, question_id=attempt.question_id,
                       response=attempt.response, feedback=feedback, feedback_job_id=job_id)


def record_attempt(db: Session, session_id: UUID, data: AttemptCreate) -> AttemptRead:
    with db.begin():
        require_session(db, session_id, lock=True)
        question = db.get(ReviewQuestion, data.question_id)
        if question is None or question.review_session_id != session_id:
            raise Conflict("Question does not belong to this review session")
        previous = db.scalar(select(ReviewAttempt).where(ReviewAttempt.question_id == question.id))
        if previous:
            if previous.response != data.response:
                raise Conflict("This question already has a different answer")
            return attempt_read(db, previous)
        reference = db.get(ExplanationRevision, question.revision_id)
        if reference is None or reference.retracted_at:
            raise Conflict("This question's explanation was undone")
        attempt = ReviewAttempt(review_session_id=session_id, question_id=question.id, format="cue_card",
                                prompt=question.prompt, response=data.response)
        db.add(attempt)
        db.flush()
        db.add(ReviewAttemptConcept(review_attempt_id=attempt.id, concept_id=question.concept_id))
        question.answered_at = datetime.now(timezone.utc)
        enqueue(db, dedup_key=f"review-feedback:{attempt.id}", kind="review_feedback", attempt_id=attempt.id)
        result = attempt_read(db, attempt)
    return result


def get_attempt(db: Session, attempt_id: UUID) -> AttemptRead:
    attempt = db.get(ReviewAttempt, attempt_id)
    if attempt is None:
        raise NotFound("Review attempt not found")
    return attempt_read(db, attempt)


def finish_session(db: Session, session_id: UUID):
    with db.begin():
        session = require_session(db, session_id, lock=True)
        session.finished_at = datetime.now(timezone.utc)
