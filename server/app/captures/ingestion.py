"""Immediate capture storage and background, automatic organization."""

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.embeddings import embed
from app.captures.ai_schemas import CaptureOutput
from app.captures.models import AIProposal, Capture, Conversation
from app.captures.schemas import CaptureReceipt, ConversationRead, QuickCapture
from app.errors import Conflict, NotConfigured, NotFound, Unavailable
from app.jobs.models import WorkItem
from app.jobs.service import enqueue_capture, enqueue_embedding
from app.knowledge.models import CaptureConcept, Concept, ConceptEmbedding, ConceptResource, ExplanationRevision, Resource
from app.learning.models import Subject
from app.learning.organisation import assign, ensure_subject, subject_index
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


def save_bookmarks(db: Session, capture: Capture) -> None:
    """Save links in capture as resources, without implying the user learned their content."""
    urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", capture.raw_text)))[:20]
    for uri in urls:
        db.add(Resource(capture_id=capture.id, kind="site", uri=uri.rstrip(".,;!?)]}")))
    db.flush()


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
            save_bookmarks(db, capture)
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
    return ConversationRead(id=conversation.id, title=conversation.title, subject_id=conversation.subject_id,
                            captures=rows[:limit], next_cursor=next_cursor)


# The local chat model has an 8k-token window shared by instructions, schema and output.
MAX_CANDIDATES = 10
CANDIDATE_CHARACTERS = 600
SEMANTIC_MINIMUM = 0.6
# Document-to-document cosine at which a "new" understanding is attached to an existing
# concept. Set for Nomic; recheck on a few real paraphrases when the embedding model changes.
MERGE_MINIMUM = 0.85


def query_vector(engine, raw_text: str) -> tuple[list[float], str] | None:
    """Embed raw_text as a retrieval query outside any transaction.

    Returns (vector, profile_key), or None when embeddings are unavailable or no saved
    explanation has a vector yet; retrieval then falls back to conversation and title matches.
    """
    from app.setup.profiles import active_profile
    try:
        with Session(engine) as db, db.begin():
            profile = active_profile(db)
            if not db.scalar(select(exists().where(ConceptEmbedding.model_key == profile.key))):
                return None
        return embed(raw_text[:4000], profile, query=True), profile.key
    except (NotConfigured, Unavailable):
        return None


def capture_context(db: Session, capture: Capture, query: tuple[list[float], str] | None = None) -> dict:
    """Bound context to this conversation, title matches and semantically similar saved ideas.

    query is an optional (vector, profile_key) for the message; it lets a paraphrase saved
    in another conversation be recognised as the same concept instead of a duplicate.
    """
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
    titled = func.strpos(func.lower(capture.raw_text), func.lower(Concept.title)) > 0
    concepts = list(db.scalars(select(Concept).where(Concept.archived_at.is_(None), Concept.id.in_(linked) | titled)
        .order_by(case((titled, 0), else_=1), Concept.created_at.desc(), Concept.id.desc()).limit(MAX_CANDIDATES)).all())
    if query is not None:
        from app.discovery.service import vector_search
        for hit in vector_search(db, query[0], query[1], 6):
            if hit.similarity is not None and hit.similarity >= SEMANTIC_MINIMUM and all(c.id != hit.id for c in concepts):
                concepts.append(db.get(Concept, hit.id))
    existing = []
    for concept in concepts[:MAX_CANDIDATES]:
        revision = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == concept.id,
            ExplanationRevision.retracted_at.is_(None)).order_by(ExplanationRevision.revision_number.desc()).limit(1))
        if revision:
            body = revision.body if len(revision.body) <= CANDIDATE_CHARACTERS else revision.body[:CANDIDATE_CHARACTERS] + " …"
            existing.append({"id": str(concept.id), "title": concept.title, "revision_id": str(revision.id), "explanation": body})
    subject = db.get(Subject, conversation.subject_id) if conversation and conversation.subject_id else None
    subjects = [{"title": row.title, "aliases": row.aliases[:5]}
                for row in db.scalars(select(Subject).order_by(Subject.title, Subject.id).limit(60)).all()]
    questions = db.scalars(select(AIProposal).join(Capture, Capture.id == AIProposal.capture_id).where(
        Capture.conversation_id == capture.conversation_id, Capture.status != "archived",
        AIProposal.kind == "clarification", AIProposal.status == "pending")
        .order_by(AIProposal.created_at.desc()).limit(5)).all()
    if capture.reply_to_proposal_id and all(row.id != capture.reply_to_proposal_id for row in questions):
        explicit = db.get(AIProposal, capture.reply_to_proposal_id)
        if explicit and explicit.status == "pending":
            questions.append(explicit)
    return {"topic": conversation.title if conversation else None,
            "conversation_subject": subject.title if subject else None, "subjects": subjects,
            "previous_user_messages": [row.raw_text[:1000] for row in reversed(history)], "existing_concepts": existing,
            "pending_clarifications": [{"id": str(row.id), "questions": row.payload.get("questions", [])} for row in questions],
            "reply_to_proposal_id": str(capture.reply_to_proposal_id) if capture.reply_to_proposal_id else None}


def attach_paraphrases(engine, raw_text: str, output: CaptureOutput, context: dict) -> CaptureOutput:
    """Point new understandings at an existing concept whose current explanation means the same.

    The capture model decides identity from the candidates it was shown; this catches the
    paraphrases it labels as new, so one idea keeps one concept and one current vector.
    Embedding happens outside any transaction. Without vectors the output is unchanged.
    """
    fresh = [index for index, item in enumerate(output.understandings) if item.existing_concept_id is None
             and all(excerpt in raw_text for excerpt in item.source_excerpts)]
    if not fresh:
        return output
    from app.discovery.service import vector_search
    from app.setup.profiles import active_profile
    try:
        with Session(engine) as db, db.begin():
            profile = active_profile(db)
            if not db.scalar(select(exists().where(ConceptEmbedding.model_key == profile.key))):
                return output
        vectors = {index: embed(source_explanation(raw_text, output.understandings[index].source_excerpts)[:4000], profile)
                   for index in fresh}
    except (NotConfigured, Unavailable):
        return output
    taken = {item.existing_concept_id for item in output.understandings if item.existing_concept_id}
    known = {row["id"] for row in context["existing_concepts"]}
    understandings, attached = list(output.understandings), []
    with Session(engine) as db:
        for index, vector in vectors.items():
            hit = next(iter(vector_search(db, vector, profile.key, 1)), None)
            if hit is None or hit.similarity is None or hit.similarity < MERGE_MINIMUM or hit.id in taken:
                continue
            if str(hit.id) not in known:
                body = db.get(ExplanationRevision, hit.revision_id).body
                context["existing_concepts"].append({"id": str(hit.id), "title": hit.title, "revision_id": str(hit.revision_id),
                                                     "explanation": body[:CANDIDATE_CHARACTERS]})
                known.add(str(hit.id))
            understandings[index] = understandings[index].model_copy(update={"existing_concept_id": hit.id})
            taken.add(hit.id)
            attached.append({"proposed_title": understandings[index].title, "concept_id": str(hit.id),
                             "similarity": round(hit.similarity, 3)})
    context["attached_by_similarity"] = attached
    return output.model_copy(update={"understandings": understandings})


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


def source_explanation(raw_text: str, excerpts: list[str], previous: str = "") -> str:
    """Keep complete user sentences containing excerpts, appending to previous saved wording."""
    ranges = []
    for excerpt in excerpts:
        start = raw_text.index(excerpt)
        end = start + len(excerpt)
        left = list(re.finditer(r"[.!?]\s+|\n+", raw_text[:start]))
        start = left[-1].end() if left else 0
        if raw_text[end - 1] not in ".!?":
            right = re.search(r"[.!?](?=\s|$)|\n", raw_text[end:])
            end = end + right.start() + (1 if right.group() != "\n" else 0) if right else len(raw_text)
        ranges.append((start, end))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    pieces = [previous] if previous else []
    for start, end in merged:
        phrase = raw_text[start:end].strip()
        if phrase and phrase not in previous:
            pieces.append(phrase)
    return "\n\n".join(pieces)


def apply_output(db: Session, capture: Capture, output: CaptureOutput, context: dict, model_key: str, prompt_version: str):
    """Caller holds the capture/work locks and owns this atomic transaction."""
    validate_sources(output, capture.raw_text, context)
    previous_by_id = {UUID(row["id"]): UUID(row["revision_id"]) for row in context["existing_concepts"]}
    # Lock targets in a stable order before making any changes.
    target_ids = sorted({x.existing_concept_id for x in output.understandings if x.existing_concept_id})
    previous_bodies = {}
    targets = {row.id: row for row in db.scalars(select(Concept).where(Concept.id.in_(target_ids))
                                               .order_by(Concept.id).with_for_update()).all()}
    for target_id in target_ids:
        latest = db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == target_id,
            ExplanationRevision.retracted_at.is_(None)).order_by(ExplanationRevision.revision_number.desc()).limit(1))
        if target_id not in targets or targets[target_id].archived_at or not latest or latest.id != previous_by_id[target_id]:
            raise DeferredWork("Concept context changed; regenerate using its latest explanation")
        previous_bodies[target_id] = latest.body
    applied_bodies = [source_explanation(capture.raw_text, item.source_excerpts, previous_bodies.get(item.existing_concept_id, ""))
                      for item in output.understandings]
    payload = {**output.model_dump(mode="json"),
               "context_revision_ids": {str(key): str(previous_by_id[key]) for key in target_ids},
               "application_policy": "verbatim-user-sentences.v1"}
    if context.get("attached_by_similarity"):
        payload["attached_by_similarity"] = context["attached_by_similarity"]
    for row, body in zip(payload["understandings"], applied_bodies):
        if row["explanation_text"] != body:
            row["unapplied_model_draft"] = row["explanation_text"]
        row["explanation_text"] = body
    proposal = AIProposal(capture_id=capture.id, kind="formatting", payload=payload,
                          model_key=model_key, prompt_version=prompt_version, status="accepted", application_mode="automatic")
    db.add(proposal)
    db.flush()
    conversation = db.get(Conversation, capture.conversation_id) if capture.conversation_id else None
    index = subject_index(db)
    attached_ids = {row["concept_id"] for row in context.get("attached_by_similarity", [])}
    if output.topic_subject and conversation is not None:
        conversation.subject_id = ensure_subject(db, output.topic_subject.title, output.topic_subject.aliases, index).id
    banked = []
    for item, body in zip(output.understandings, applied_bodies):
        concept = targets.get(item.existing_concept_id)
        created = concept is None
        if concept is None:
            concept = Concept(title=item.title)
            db.add(concept)
            db.flush()
        number = db.scalar(select(func.max(ExplanationRevision.revision_number)).where(ExplanationRevision.concept_id == concept.id)) or 0
        revision = ExplanationRevision(concept_id=concept.id, capture_id=capture.id, proposal_id=proposal.id,
            revision_number=number + 1,
            body=body,
            origin="ai_formatted_user_input")
        db.add(revision)
        if db.get(CaptureConcept, (capture.id, concept.id)) is None:
            db.add(CaptureConcept(capture_id=capture.id, concept_id=concept.id))
        db.flush()
        enqueue_embedding(db, revision.id)
        names = item.subjects or ([db.get(Subject, conversation.subject_id).title] if conversation and conversation.subject_id else [])
        subjects = []
        for name in names:
            subject = ensure_subject(db, name, index=index)
            assign(db, subject.id, concept.id, capture.id)
            subjects.append(subject.title)
        banked.append({"concept_id": str(concept.id), "title": concept.title, "revision_id": str(revision.id),
                       "created": created, "subjects": list(dict.fromkeys(subjects)), "body": body,
                       "same_idea": str(concept.id) in attached_ids})
    clarification_id = None
    if output.clarifications:
        clarification = AIProposal(capture_id=capture.id, kind="clarification",
            payload={"questions": [x.model_dump() for x in output.clarifications]}, model_key=model_key,
            prompt_version=prompt_version, status="pending")
        db.add(clarification)
        db.flush()
        clarification_id = str(clarification.id)
    reply_id = capture.reply_to_proposal_id or output.answered_clarification_id
    if reply_id:
        question = db.scalar(select(AIProposal).where(AIProposal.id == reply_id).with_for_update())
        if question and question.status == "pending":
            capture.reply_to_proposal_id = question.id
            question.status = "accepted"
            question.application_mode = "user"
            question.reviewed_at = datetime.now(timezone.utc)
    topic = output.topic_title or (output.topic_subject.title if output.topic_subject else None)
    if topic and conversation is not None:
        conversation.title = topic
    capture.status = "processed"
    return {"banked": banked, "topic": topic,
            "subject": db.get(Subject, conversation.subject_id).title if conversation and conversation.subject_id else None,
            "clarifications": [x.question for x in output.clarifications], "clarification_id": clarification_id}


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
