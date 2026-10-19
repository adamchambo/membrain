"""Immediate capture storage and background, automatic organization."""

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.captures.ai_schemas import CaptureOutput
from app.captures.models import AIProposal, Capture, Conversation
from app.captures.schemas import CaptureReceipt, ConversationRead, QuickCapture
from app.errors import Conflict, NotFound, Unavailable
from app.jobs.models import WorkItem
from app.jobs.service import enqueue_capture, enqueue_embedding
from app.knowledge.models import CaptureConcept, Concept, ConceptResource, ExplanationRevision, Resource
from app.pagination import before_cursor, encode_cursor


class DeferredWork(Exception):
    """A predecessor or changed context requires another processing attempt."""


def receipt(db: Session, capture: Capture) -> CaptureReceipt:
    job_id = db.scalar(select(WorkItem.id).where(WorkItem.capture_id == capture.id, WorkItem.kind == "capture"))
    resources = db.scalars(select(Resource.id).where(Resource.capture_id == capture.id, Resource.archived_at.is_(None))).all()
    return CaptureReceipt(capture_id=capture.id, conversation_id=capture.conversation_id,
                          processing_job_id=job_id, resource_ids=resources)


def _existing_request(db: Session, data: QuickCapture) -> Capture | None:
    if data.request_id is None:
        return None
    capture = db.scalar(select(Capture).where(Capture.request_id == data.request_id))
    if capture and (capture.raw_text != data.raw_text or capture.input_kind != data.input_kind or
                    (data.reply_to_proposal_id is not None and capture.reply_to_proposal_id != data.reply_to_proposal_id) or
                    (data.conversation_id is not None and capture.conversation_id != data.conversation_id)):
        raise Conflict("This request_id was already used for a different message")
    return capture


def ingest(db: Session, data: QuickCapture) -> CaptureReceipt:
    try:
        with db.begin():
            previous = _existing_request(db, data)
            if previous:
                return receipt(db, previous)
            conversation = db.get(Conversation, data.conversation_id) if data.conversation_id else Conversation()
            if conversation is None:
                raise NotFound("Conversation not found")
            db.add(conversation)
            db.flush()
            if data.reply_to_proposal_id:
                question = db.get(AIProposal, data.reply_to_proposal_id)
                source = db.get(Capture, question.capture_id) if question else None
                if not question or question.kind != "clarification" or question.status != "pending" or not source or source.conversation_id != conversation.id:
                    raise Conflict("Clarification must be pending and belong to this conversation")
            capture = Capture(raw_text=data.raw_text, input_kind=data.input_kind,
                              conversation_id=conversation.id, request_id=data.request_id,
                              reply_to_proposal_id=data.reply_to_proposal_id, status="pending")
            db.add(capture)
            db.flush()
            enqueue_capture(db, capture.id)
            # Bookmarks are saved without implying the user learned their content.
            urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", data.raw_text)))[:20]
            for uri in urls:
                db.add(Resource(capture_id=capture.id, kind="site", uri=uri.rstrip(".,;!?)]}")))
            db.flush()
            return receipt(db, capture)
    except IntegrityError:
        # Concurrent retries of the same request can race on its unique key.
        with db.begin():
            previous = _existing_request(db, data)
            if previous:
                return receipt(db, previous)
        raise


def conversation_history(db: Session, conversation_id: UUID, cursor: str | None, limit: int) -> ConversationRead:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found")
    query = select(Capture).where(Capture.conversation_id == conversation_id)
    if cursor:
        query = query.where(before_cursor(Capture.created_at, Capture.id, cursor))
    rows = db.scalars(query.order_by(Capture.created_at.desc(), Capture.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return ConversationRead(id=conversation.id, title=conversation.title, captures=rows[:limit], next_cursor=next_cursor)


def capture_context(db: Session, capture: Capture) -> dict:
    """Bound context to this conversation and a small number of title matches."""
    predecessor = db.scalar(select(WorkItem.id).join(Capture, WorkItem.capture_id == Capture.id).where(
        Capture.conversation_id == capture.conversation_id, Capture.id != capture.id,
        (Capture.created_at < capture.created_at) | ((Capture.created_at == capture.created_at) & (Capture.id < capture.id)),
        WorkItem.kind == "capture", WorkItem.status.in_(["pending", "running"])).limit(1))
    if predecessor:
        raise DeferredWork("Earlier conversation messages are still processing")
    conversation = db.get(Conversation, capture.conversation_id)
    history = db.scalars(select(Capture).where(Capture.conversation_id == capture.conversation_id,
        Capture.created_at <= capture.created_at, Capture.id != capture.id, Capture.status == "processed")
        .order_by(Capture.created_at.desc(), Capture.id.desc()).limit(6)).all()
    linked = select(CaptureConcept.concept_id).join(Capture, CaptureConcept.capture_id == Capture.id).where(
        Capture.conversation_id == capture.conversation_id, Capture.status != "archived")
    concepts = db.scalars(select(Concept).where(Concept.archived_at.is_(None),
        (Concept.id.in_(linked)) | (func.strpos(func.lower(capture.raw_text), func.lower(Concept.title)) > 0))
        .order_by(case((func.strpos(func.lower(capture.raw_text), func.lower(Concept.title)) > 0, 0), else_=1),
                  Concept.created_at.desc(), Concept.id.desc()).limit(20)).all()
    existing = []
    remaining_characters = 24000
    for concept in concepts:
        revision = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == concept.id,
            ExplanationRevision.retracted_at.is_(None)).order_by(ExplanationRevision.revision_number.desc()).limit(1))
        if revision and len(revision.body) <= remaining_characters:
            existing.append({"id": str(concept.id), "title": concept.title, "revision_id": str(revision.id),
                             "explanation": revision.body})
            remaining_characters -= len(revision.body)
    questions = db.scalars(select(AIProposal).join(Capture, Capture.id == AIProposal.capture_id).where(
        Capture.conversation_id == capture.conversation_id, Capture.status != "archived",
        AIProposal.kind == "clarification", AIProposal.status == "pending")
        .order_by(AIProposal.created_at.desc()).limit(5)).all()
    if capture.reply_to_proposal_id and all(row.id != capture.reply_to_proposal_id for row in questions):
        explicit = db.get(AIProposal, capture.reply_to_proposal_id)
        if explicit and explicit.status == "pending":
            questions.append(explicit)
    return {"topic": conversation.title if conversation else None,
            "previous_user_messages": [row.raw_text[:4000] for row in reversed(history)], "existing_concepts": existing,
            "pending_clarifications": [{"id": str(row.id), "questions": row.payload.get("questions", [])} for row in questions],
            "reply_to_proposal_id": str(capture.reply_to_proposal_id) if capture.reply_to_proposal_id else None}


def validate_sources(output: CaptureOutput, raw_text: str, context: dict) -> None:
    allowed_ids = {UUID(row["id"]) for row in context["existing_concepts"]}
    for understanding in output.understandings:
        if any(excerpt not in raw_text for excerpt in understanding.source_excerpts):
            raise Unavailable("The capture result referenced text outside the original message")
        if understanding.existing_concept_id and understanding.existing_concept_id not in allowed_ids:
            raise Unavailable("The capture result referenced a concept outside its supplied context")
    if any(question.source_excerpt not in raw_text for question in output.clarifications):
        raise Unavailable("A clarification referenced text outside the original message")
    question_ids = {UUID(row["id"]) for row in context.get("pending_clarifications", [])}
    if output.answered_clarification_id and output.answered_clarification_id not in question_ids:
        raise Unavailable("The result referenced a clarification outside its supplied context")


def apply_output(db: Session, capture: Capture, output: CaptureOutput, context: dict, model_key: str, prompt_version: str):
    """Caller holds the capture/work locks and owns this atomic transaction."""
    validate_sources(output, capture.raw_text, context)
    previous_by_id = {UUID(row["id"]): UUID(row["revision_id"]) for row in context["existing_concepts"]}
    # Lock targets in a stable order before making any changes.
    target_ids = sorted({x.existing_concept_id for x in output.understandings if x.existing_concept_id})
    targets = {row.id: row for row in db.scalars(select(Concept).where(Concept.id.in_(target_ids))
                                               .order_by(Concept.id).with_for_update()).all()}
    for target_id in target_ids:
        latest = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == target_id,
            ExplanationRevision.retracted_at.is_(None)).order_by(ExplanationRevision.revision_number.desc()).limit(1))
        if target_id not in targets or targets[target_id].archived_at or not latest or latest.id != previous_by_id[target_id]:
            raise DeferredWork("Concept context changed; regenerate using its latest explanation")
    payload = {**output.model_dump(mode="json"),
               "context_revision_ids": {str(key): str(previous_by_id[key]) for key in target_ids}}
    proposal = AIProposal(capture_id=capture.id, kind="formatting", payload=payload,
                          model_key=model_key, prompt_version=prompt_version, status="accepted", application_mode="automatic")
    db.add(proposal)
    db.flush()
    for item in output.understandings:
        concept = targets.get(item.existing_concept_id)
        if concept is None:
            concept = Concept(title=item.title)
            db.add(concept)
            db.flush()
        number = db.scalar(select(func.max(ExplanationRevision.revision_number)).where(ExplanationRevision.concept_id == concept.id)) or 0
        revision = ExplanationRevision(concept_id=concept.id, capture_id=capture.id, proposal_id=proposal.id,
            revision_number=number + 1, body=item.explanation_text, origin="ai_formatted_user_input")
        db.add(revision)
        if db.get(CaptureConcept, (capture.id, concept.id)) is None:
            db.add(CaptureConcept(capture_id=capture.id, concept_id=concept.id))
        db.flush()
        enqueue_embedding(db, revision.id)
    if output.clarifications:
        db.add(AIProposal(capture_id=capture.id, kind="clarification",
            payload={"questions": [x.model_dump() for x in output.clarifications]}, model_key=model_key,
            prompt_version=prompt_version, status="pending"))
    reply_id = capture.reply_to_proposal_id or output.answered_clarification_id
    if reply_id:
        question = db.scalar(select(AIProposal).where(AIProposal.id == reply_id).with_for_update())
        if question and question.status == "pending":
            capture.reply_to_proposal_id = question.id
            question.status = "accepted"
            question.application_mode = "user"
            question.reviewed_at = datetime.now(timezone.utc)
    if output.topic_title and capture.conversation_id:
        conversation = db.get(Conversation, capture.conversation_id)
        conversation.title = output.topic_title
    capture.status = "processed"


def undo_capture(db: Session, capture_id: UUID) -> None:
    with db.begin():
        jobs = db.scalars(select(WorkItem).where(WorkItem.capture_id == capture_id)
                          .order_by(WorkItem.id).with_for_update()).all()
        capture = db.scalar(select(Capture).where(Capture.id == capture_id).with_for_update())
        if capture is None:
            raise NotFound("Capture not found")
        if capture.status == "archived":
            return
        revisions = db.scalars(select(ExplanationRevision).where(ExplanationRevision.capture_id == capture_id,
            ExplanationRevision.retracted_at.is_(None))).all()
        ids = sorted({r.concept_id for r in revisions})
        concepts = db.scalars(select(Concept).where(Concept.id.in_(ids)).order_by(Concept.id).with_for_update()).all()
        for concept in concepts:
            latest = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == concept.id,
                ExplanationRevision.retracted_at.is_(None)).order_by(ExplanationRevision.revision_number.desc()).limit(1))
            if latest and latest.capture_id != capture_id:
                raise Conflict("This capture has newer dependent explanations; edit the current explanation instead")
        now = datetime.now(timezone.utc)
        for revision in revisions:
            revision.retracted_at = now
        db.flush()
        for concept in concepts:
            active = db.scalar(select(ExplanationRevision.id).where(ExplanationRevision.concept_id == concept.id,
                               ExplanationRevision.retracted_at.is_(None)).limit(1))
            if active is None:
                concept.archived_at = now
        for resource in db.scalars(select(Resource).where(Resource.capture_id == capture_id)).all():
            if db.scalar(select(ConceptResource.resource_id).where(ConceptResource.resource_id == resource.id).limit(1)) is None:
                resource.archived_at = now
        for job in jobs:
            if job.status in ("pending", "running"):
                job.status = "cancelled"
                job.lease_token = None
        for proposal in db.scalars(select(AIProposal).where(AIProposal.capture_id == capture_id,
                                  AIProposal.status == "pending").with_for_update()).all():
            proposal.status = "rejected"
            proposal.application_mode = "user"
            proposal.reviewed_at = now
        if capture.reply_to_proposal_id:
            other_reply = db.scalar(select(Capture.id).where(Capture.reply_to_proposal_id == capture.reply_to_proposal_id,
                Capture.id != capture.id, Capture.status == "processed").limit(1))
            question = db.scalar(select(AIProposal).where(AIProposal.id == capture.reply_to_proposal_id).with_for_update())
            source = db.get(Capture, question.capture_id) if question else None
            if not other_reply and question and source and source.status != "archived" and question.kind == "clarification":
                question.status = "pending"
                question.application_mode = None
                question.reviewed_at = None
        capture.status = "archived"
