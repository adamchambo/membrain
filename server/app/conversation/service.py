"""Save each turn before any inference; processing happens in the durable worker."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.captures.ingestion import save_bookmarks
from app.captures.models import Capture, Conversation
from app.conversation.models import ConversationTurn
from app.conversation.processor import compose
from app.conversation.schemas import ActiveQuestion, TurnCreate, TurnPage, TurnRead
from app.conversation.scope import zone
from app.errors import Conflict, NotFound
from app.jobs.models import WorkItem
from app.jobs.service import enqueue, retry_work


def activity(conversation: Conversation | None) -> ActiveQuestion | None:
    state = conversation.active_activity if conversation else None
    if not state:
        return None
    return ActiveQuestion(type=state["type"], format=state.get("format"), question=state["question"],
                        options=state.get("options") or [], number=state.get("number"), target=state.get("target"))


def read(db: Session, turn: ConversationTurn, conversation: Conversation | None = None) -> TurnRead:
    capture = db.get(Capture, turn.capture_id)
    job = db.scalar(select(WorkItem).where(WorkItem.dedup_key == f"turn:{turn.id}"))
    if turn.completed_at:
        status, error = "completed", None
    elif job is None or job.status in ("failed", "cancelled"):
        status, error = "failed", (job.last_error if job else None) or "Processing stopped; retry this message"
    else:
        status, error = "processing", job.last_error
    banked = [UUID(row["concept_id"]) for effect in turn.effects.values() for row in effect.get("banked", [])]
    reply = turn.reply
    if status == "failed" and turn.effects:
        # Completed intents are durable even when a later one failed; show what happened.
        reply = compose(turn.effects)
    return TurnRead(id=turn.id, conversation_id=turn.conversation_id, capture_id=turn.capture_id, sequence=turn.sequence,
                    message=capture.raw_text, status=status, progress=turn.progress, reply=reply, error=error,
                    job_id=job.id if job else None, banked_concept_ids=banked,
                    active_question=activity(conversation or db.get(Conversation, turn.conversation_id)),
                    created_at=turn.created_at, completed_at=turn.completed_at)


def _existing(db: Session, data: TurnCreate) -> ConversationTurn | None:
    capture = db.scalar(select(Capture).where(Capture.request_id == data.client_message_id))
    if capture is None:
        return None
    turn = db.scalar(select(ConversationTurn).where(ConversationTurn.capture_id == capture.id))
    if turn is None or capture.raw_text != data.text or (data.conversation_id and capture.conversation_id != data.conversation_id):
        raise Conflict("This client_message_id was already used for a different message")
    return turn


def submit(db: Session, data: TurnCreate) -> TurnRead:
    """Persist data's verbatim text and an ordered turn, then queue its processing."""
    try:
        with db.begin():
            turn = _existing(db, data)
            if turn is None:
                if data.conversation_id:
                    conversation = db.scalar(select(Conversation).where(Conversation.id == data.conversation_id).with_for_update())
                    if conversation is None:
                        raise NotFound("Conversation not found")
                else:
                    conversation = Conversation()
                    db.add(conversation)
                    db.flush()
                sequence = (db.scalar(select(func.max(ConversationTurn.sequence))
                                      .where(ConversationTurn.conversation_id == conversation.id)) or 0) + 1
                capture = Capture(raw_text=data.text, input_kind=data.input_kind, conversation_id=conversation.id,
                                  request_id=data.client_message_id, status="pending")
                db.add(capture)
                db.flush()
                save_bookmarks(db, capture)
                turn = ConversationTurn(conversation_id=conversation.id, capture_id=capture.id, sequence=sequence,
                                        timezone=zone(data.timezone).key, progress=[], effects={})
                db.add(turn)
                db.flush()
                enqueue(db, dedup_key=f"turn:{turn.id}", kind="turn", arguments={"turn_id": str(turn.id)})
            return read(db, turn)
    except IntegrityError:
        # Concurrent retries of one message race on its unique request key.
        with db.begin():
            turn = _existing(db, data)
            if turn:
                return read(db, turn)
        raise


def get(db: Session, turn_id: UUID) -> TurnRead:
    turn = db.get(ConversationTurn, turn_id)
    if turn is None:
        raise NotFound("Turn not found")
    return read(db, turn)


def history(db: Session, conversation_id: UUID, before: int | None, limit: int) -> TurnPage:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found")
    query = select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id)
    if before is not None:
        query = query.where(ConversationTurn.sequence < before)
    rows = db.scalars(query.order_by(ConversationTurn.sequence.desc()).limit(limit + 1)).all()
    items = [read(db, row, conversation) for row in reversed(rows[:limit])]
    return TurnPage(items=items, next_before=items[0].sequence if len(rows) > limit else None)


def retry(db: Session, turn_id: UUID) -> TurnRead:
    with db.begin():
        turn = db.get(ConversationTurn, turn_id)
        if turn is None:
            raise NotFound("Turn not found")
        completed = turn.completed_at is not None
        job_id = db.scalar(select(WorkItem.id).where(WorkItem.dedup_key == f"turn:{turn.id}"))
    if not completed:
        if job_id is None:
            raise Conflict("This turn has no processing record")
        retry_work(db, job_id)
    with db.begin():
        return read(db, db.get(ConversationTurn, turn_id))
