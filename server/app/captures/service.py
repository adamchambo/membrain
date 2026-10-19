"""Capture, formatting, and banking rules; no HTTP handling here."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.ai.formatter import FormatCandidate, Formatter
from app.captures.models import AIProposal, Capture
from app.captures.schemas import BankCapture, BankResult, CaptureCreate
from app.errors import Conflict, NotFound
from app.knowledge.models import CaptureConcept, Concept, ExplanationRevision
from app.pagination import before_cursor, encode_cursor
from app.jobs.service import enqueue_embedding
from app.captures.prompts.formatting import FORMAT_VERSION
from app.jobs.models import WorkItem


def create_capture(db: Session, data: CaptureCreate) -> Capture:
    with db.begin():
        capture = Capture(raw_text=data.raw_text, input_kind=data.input_kind, status="pending")
        db.add(capture)
        db.flush()
    return capture


def list_captures(db: Session, status: str | None, cursor: str | None, limit: int):
    statement = select(Capture)
    if status:
        statement = statement.where(Capture.status == status)
    if cursor:
        statement = statement.where(before_cursor(Capture.created_at, Capture.id, cursor))
    rows = db.scalars(statement.order_by(Capture.created_at.desc(), Capture.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_capture(db: Session, capture_id: UUID):
    capture = db.get(Capture, capture_id)
    if capture is None:
        raise NotFound("Capture not found")
    concept_ids = db.scalars(select(CaptureConcept.concept_id).where(CaptureConcept.capture_id == capture_id)).all()
    proposals = db.scalars(
        select(AIProposal).where(AIProposal.capture_id == capture_id).order_by(AIProposal.created_at.desc(), AIProposal.id.desc())
    ).all()
    return capture, concept_ids, proposals


def format_capture(db: Session, capture_id: UUID, formatter: Formatter) -> AIProposal:
    with db.begin():
        capture = db.get(Capture, capture_id)
        if capture is None:
            raise NotFound("Capture not found")
        if capture.status == "archived":
            raise Conflict("Archived captures cannot be formatted")
        raw_text = capture.raw_text

    candidate = formatter.format(raw_text)
    with db.begin():
        current = db.scalar(select(Capture).where(Capture.id == capture_id).with_for_update().execution_options(populate_existing=True))
        if current is None:
            raise NotFound("Capture not found")
        if current.status == "archived":
            raise Conflict("Archived captures cannot be formatted")
        proposal = AIProposal(
            capture_id=capture_id,
            kind="formatting",
            payload=candidate.model_dump(),
            model_key=formatter.model_key,
            prompt_version=FORMAT_VERSION,
            status="pending",
        )
        db.add(proposal)
        db.flush()
    return proposal


def list_proposals(db: Session, capture_id: UUID, kind: str | None, cursor: str | None, limit: int):
    if db.get(Capture, capture_id) is None:
        raise NotFound("Capture not found")
    statement = select(AIProposal).where(AIProposal.capture_id == capture_id)
    if kind:
        statement = statement.where(AIProposal.kind == kind)
    if cursor:
        statement = statement.where(before_cursor(AIProposal.created_at, AIProposal.id, cursor))
    rows = db.scalars(statement.order_by(AIProposal.created_at.desc(), AIProposal.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def bank_capture(db: Session, capture_id: UUID, data: BankCapture) -> BankResult:
    with db.begin():
        capture = db.scalar(select(Capture).where(Capture.id == capture_id).with_for_update())
        if capture is None:
            raise NotFound("Capture not found")
        if capture.status == "archived":
            raise Conflict("Archived captures cannot be banked")

        proposal = None
        if data.formatting_proposal_id:
            proposal = db.scalar(
                select(AIProposal).where(AIProposal.id == data.formatting_proposal_id).with_for_update()
            )
            if proposal is None or proposal.capture_id != capture_id or proposal.kind != "formatting":
                raise Conflict("Formatting proposal does not belong to this capture")
            if proposal.status != "pending":
                raise Conflict("Formatting proposal is already resolved")
            try:
                candidate = FormatCandidate.model_validate(proposal.payload)
            except ValidationError as exc:
                raise Conflict("Formatting proposal payload is invalid") from exc
            origin = (
                "ai_formatted_user_input"
                if data.explanation_text == candidate.explanation_text
                else "user_edited_format"
            )
        else:
            origin = "user_written"

        if data.concept_id:
            concept = db.scalar(select(Concept).where(Concept.id == data.concept_id).with_for_update())
            if concept is None:
                raise NotFound("Concept not found")
            if concept.archived_at is not None:
                raise Conflict("Archived concepts cannot receive new explanations")
        else:
            concept = Concept(title=data.new_title)
            db.add(concept)
            db.flush()

        latest_number = db.scalar(
            select(ExplanationRevision.revision_number)
            .where(ExplanationRevision.concept_id == concept.id)
            .order_by(ExplanationRevision.revision_number.desc())
            .limit(1)
        )
        revision = ExplanationRevision(
            concept_id=concept.id,
            capture_id=capture_id,
            proposal_id=proposal.id if proposal else None,
            revision_number=(latest_number or 0) + 1,
            body=data.explanation_text.strip(),
            origin=origin,
        )
        db.add(revision)
        if db.get(CaptureConcept, (capture_id, concept.id)) is None:
            db.add(CaptureConcept(capture_id=capture_id, concept_id=concept.id))
        capture.status = "processed"
        if proposal:
            proposal.status = "accepted"
            proposal.application_mode = "user"
            proposal.reviewed_at = datetime.now(timezone.utc)
        db.flush()
        job_id = enqueue_embedding(db, revision.id)
        result = BankResult(concept_id=concept.id, revision_id=revision.id, origin=origin,
                            embedding_status="pending" if db.get(WorkItem, job_id).profile_key else "not_configured")
    return result


def reject_proposal(db: Session, proposal_id: UUID) -> AIProposal:
    with db.begin():
        proposal = db.scalar(select(AIProposal).where(AIProposal.id == proposal_id).with_for_update())
        if proposal is None:
            raise NotFound("Proposal not found")
        if proposal.status != "pending":
            raise Conflict("Proposal is already resolved")
        proposal.status = "rejected"
        proposal.reviewed_at = datetime.now(timezone.utc)
    return proposal
