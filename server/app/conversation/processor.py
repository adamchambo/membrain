"""Process one turn: interpret, then run a fixed recipe per intent, in order.

Each recipe does its inference outside any transaction, then applies its durable writes
and records its effect in one lease-fenced transaction. A retried job skips intents
whose effect is recorded, so bank writes, questions and answers happen at most once.
"""

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.ai.client import ChatClient, get_chat_client
from app.ai.structured import generate
from app.captures.formatter import CaptureAI
from app.captures.ingestion import DeferredWork, apply_output, attach_paraphrases, capture_context, query_vector
from app.captures.models import Capture, Conversation
from app.captures.prompts.formatting import CAPTURE_VERSION
from app.conversation.interpret import Intent, RouterOutput, route
from app.conversation.models import ConversationTurn
from app.jobs.models import WorkItem
from app.learning.models import Subject

LEASE_SECONDS = 180


class LeaseLost(Exception):
    """Another worker now owns this job; stop without writing."""


class TurnRun:
    def __init__(self, engine: Engine, job_id: UUID, token: UUID, client: ChatClient | None = None):
        """Run the turn named by job_id while holding lease token; client injects a chat model."""
        self.engine, self.job_id, self.token = engine, job_id, token
        self._client = client
        with Session(engine) as db:
            job = db.get(WorkItem, job_id)
            turn = db.get(ConversationTurn, UUID(job.arguments["turn_id"]))
            capture = db.get(Capture, turn.capture_id)
            conversation = db.get(Conversation, turn.conversation_id)
            self.turn_id, self.conversation_id, self.capture_id = turn.id, turn.conversation_id, turn.capture_id
            self.sequence, self.timezone, self.message = turn.sequence, turn.timezone, capture.raw_text
            self.effects, self.intents, self.completed = dict(turn.effects), turn.intents, turn.completed_at is not None
            self.active = conversation.active_activity

    @property
    def client(self) -> ChatClient:
        if self._client is None:
            self._client = get_chat_client()
        return self._client

    def fenced(self, apply: Callable[[Session], object]):
        """Run apply(db) in one transaction only while this worker still owns the job."""
        from app.jobs.worker import owned_job
        with Session(self.engine) as db, db.begin():
            job = owned_job(db, self.job_id, self.token)
            if job is None:
                raise LeaseLost()
            job.lease_until = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
            return apply(db)

    def note(self, text: str) -> None:
        """Append a user-visible progress step; also renews the lease before slow inference."""
        def apply(db):
            turn = db.get(ConversationTurn, self.turn_id)
            turn.progress = [*turn.progress, {"at": datetime.now(timezone.utc).isoformat(), "text": text}]
        self.fenced(apply)

    def ask(self, prompt: str, payload: dict, schema, failure: str):
        return generate(self.client, prompt, payload, schema, failure=failure)

    def vector(self, text: str):
        return query_vector(self.engine, text)

    def complete(self, index: int, apply: Callable[[Session], dict]) -> dict:
        """Apply an intent's writes and record its effect atomically; apply returns the effect."""
        def write(db):
            turn = db.scalar(select(ConversationTurn).where(ConversationTurn.id == self.turn_id).with_for_update())
            if str(index) in turn.effects:
                return turn.effects[str(index)]
            effect = apply(db)
            turn.effects = {**turn.effects, str(index): effect}
            conversation = db.get(Conversation, self.conversation_id)
            self.active = conversation.active_activity
            return effect
        effect = self.fenced(write)
        self.effects[str(index)] = effect
        return effect

    def context_ids(self) -> list[UUID]:
        """Concepts this turn just banked or used, else those used by the latest earlier turn."""
        def concepts(effects: dict) -> list[UUID]:
            ids = []
            for key in sorted(effects, key=int):
                effect = effects[key]
                ids.extend(UUID(row["concept_id"]) for row in effect.get("banked", []))
                ids.extend(UUID(x) for x in effect.get("concept_ids", []))
            return list(dict.fromkeys(ids))
        current = concepts(self.effects)
        if current:
            return current
        with Session(self.engine) as db:
            for turn in db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == self.conversation_id,
                                   ConversationTurn.sequence < self.sequence, ConversationTurn.completed_at.is_not(None))
                                   .order_by(ConversationTurn.sequence.desc()).limit(5)).all():
                found = concepts(turn.effects)
                if found:
                    return found
        return []

    def router_context(self) -> dict:
        with Session(self.engine) as db:
            conversation = db.get(Conversation, self.conversation_id)
            subject = db.get(Subject, conversation.subject_id) if conversation.subject_id else None
            rows = db.execute(select(ConversationTurn, Capture.raw_text).join(Capture, Capture.id == ConversationTurn.capture_id)
                .where(ConversationTurn.conversation_id == self.conversation_id, ConversationTurn.sequence < self.sequence)
                .order_by(ConversationTurn.sequence.desc()).limit(3)).all()
        recent = []
        for turn, text in reversed(rows):
            recent.append({"role": "user", "content": text[:400]})
            if turn.reply:
                recent.append({"role": "assistant", "content": turn.reply[:400]})
        active = None
        if self.active:
            active = {key: self.active.get(key) for key in ("type", "format", "question", "options")}
        return {"recent_turns": recent, "active_activity": active,
                "conversation_topic": subject.title if subject else conversation.title}

    def run(self) -> None:
        if self.completed:
            self.finish()
            return
        with Session(self.engine) as db:
            unfinished = db.scalars(select(ConversationTurn.id).where(ConversationTurn.conversation_id == self.conversation_id,
                ConversationTurn.sequence < self.sequence, ConversationTurn.completed_at.is_(None))).all()
            # A permanently failed earlier turn must not block the conversation forever.
            earlier = unfinished and db.scalar(select(WorkItem.id).where(
                WorkItem.dedup_key.in_([f"turn:{x}" for x in unfinished]), WorkItem.status.in_(["pending", "running"])).limit(1))
        if earlier:
            raise DeferredWork("Earlier messages in this conversation are still being processed")
        if self.intents is None:
            self.note("Reading your message")
            result = route(self.client, self.message, self.router_context())
            def save(db):
                turn = db.get(ConversationTurn, self.turn_id)
                turn.intents = {**result.model_dump(mode="json"), "version": "turn-router.v1"}
            self.fenced(save)
            self.intents = result.model_dump(mode="json")
        intents = RouterOutput.model_validate(self.intents).intents
        from app.conversation.recipes import RECIPES
        for index, intent in enumerate(intents):
            if str(index) not in self.effects:
                RECIPES[intent.action](self, index, intent, len(intents))
        self.finish()

    def finish(self) -> None:
        def apply(db):
            turn = db.scalar(select(ConversationTurn).where(ConversationTurn.id == self.turn_id).with_for_update())
            if turn.completed_at is None:
                turn.reply = compose(turn.effects)
                turn.completed_at = datetime.now(timezone.utc)
            capture = db.get(Capture, self.capture_id)
            if capture.status == "pending":
                capture.status = "processed"
            job = db.get(WorkItem, self.job_id)
            job.status, job.last_error, job.lease_token, job.lease_until = "succeeded", None, None, None
        self.fenced(apply)


def compose(effects: dict) -> str:
    parts = [effects[key].get("reply", "") for key in sorted(effects, key=int)]
    return "\n\n".join(part for part in parts if part) or "Saved."


def process_turn(engine: Engine, job_id: UUID, token: UUID, client: ChatClient | None = None) -> None:
    try:
        TurnRun(engine, job_id, token, client).run()
    except LeaseLost:
        return


def bank(run: TurnRun, index: int, intent: Intent, count: int) -> None:
    """Save the user's own statements verbatim and organise them into concepts and subjects."""
    with Session(run.engine) as db:
        pending = db.get(Capture, run.capture_id).status == "pending"
    if not pending:
        run.complete(index, lambda db: {"kind": "bank", "banked": [], "reply": ""})
        return
    run.note("Saving and organising your explanation")
    query = run.vector(run.message)
    with Session(run.engine) as db:
        context = capture_context(db, db.get(Capture, run.capture_id), query)
    output = attach_paraphrases(run.engine, run.message, CaptureAI(run.client).process(run.message, context), context)

    def apply(db):
        capture = db.scalar(select(Capture).where(Capture.id == run.capture_id).with_for_update())
        if capture.status != "pending":
            return {"kind": "bank", "banked": [], "reply": ""}
        summary = apply_output(db, capture, output, context, run.client.model_key, CAPTURE_VERSION)
        for row in summary["banked"]:
            row.pop("body", None)
        return {"kind": "bank", **summary, "reply": bank_reply(summary, alone=count == 1)}
    run.complete(index, apply)


def bank_reply(summary: dict, *, alone: bool) -> str:
    lines = []
    for row in summary["banked"]:
        where = f" (filed under {', '.join(row['subjects'])})" if row["subjects"] else ""
        if row["created"]:
            lines.append(f"Saved your explanation of “{row['title']}”{where}, in your own words.")
        elif row.get("same_idea"):
            lines.append(f"This reads as the same idea as your saved “{row['title']}”, so I added it there{where}.")
        else:
            lines.append(f"Added this to your saved understanding of “{row['title']}”{where}.")
    if not lines and summary.get("subject"):
        lines.append(f"Noted: you're learning about {summary['subject']}. Tell me what you understand so far and I'll save it in your words.")
    elif not lines and alone:
        lines.append("Saved your message. I didn't find an explanation of your own understanding in it, so nothing new was added to your bank.")
    if summary.get("clarifications"):
        lines.append("Optional question, answer whenever you like: " + summary["clarifications"][0])
    return "\n".join(lines)
