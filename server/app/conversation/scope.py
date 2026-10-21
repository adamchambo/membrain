"""Resolve conversational topic, reference and time wording into validated concept IDs.

The model only names a topic or period; IDs and date bounds are computed here, so an
activity can never act on records the user did not refer to.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone as utc_zone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.captures.models import Capture, Conversation
from app.discovery.service import latest_revisions, text_search, vector_search
from app.knowledge.models import CaptureConcept, Concept, ExplanationRevision
from app.learning.models import Subject, SubjectConcept
from app.learning.organisation import name_key

# "Recently" is a stated, adjustable default rather than a hidden heuristic.
RECENT_DAYS = 7
# Nomic query-to-document cosine similarity; topic words are short, so similarity is low.
TOPIC_MINIMUM = 0.5
TOPIC_MARGIN = 0.12
MAX_SCOPE = 30


@dataclass
class Scope:
    concept_ids: list[UUID] = field(default_factory=list)
    subject_ids: list[UUID] = field(default_factory=list)
    topic: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    period_phrase: str = ""
    considered: int = 0
    basis: str = "none"

    @property
    def description(self) -> str:
        subject = self.topic or ("this conversation" if self.basis == "context" else "everything you've saved")
        return subject + (f" {self.period_phrase}" if self.period_phrase else "")

    def as_json(self) -> dict:
        return {"concept_ids": [str(x) for x in self.concept_ids], "subject_ids": [str(x) for x in self.subject_ids],
                "topic": self.topic, "since": self.since.isoformat() if self.since else None,
                "until": self.until.isoformat() if self.until else None, "period": self.period_phrase,
                "considered": self.considered, "truncated": self.considered > len(self.concept_ids), "basis": self.basis}


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def period_bounds(period: str, days: int | None, timezone_name: str, now: datetime | None = None):
    """Return (since, until, phrase) for a period label in the user's timezone; until is exclusive."""
    tz = zone(timezone_name)
    now = (now or datetime.now(utc_zone.utc)).astimezone(tz)
    midnight = datetime.combine(now.date(), time.min, tz)
    week = midnight - timedelta(days=now.weekday())
    month = midnight.replace(day=1)
    previous_month = (month - timedelta(days=1)).replace(day=1)
    bounds = {
        "recent": (now - timedelta(days=RECENT_DAYS), None, f"over the past {RECENT_DAYS} days"),
        "today": (midnight, None, "today"),
        "yesterday": (midnight - timedelta(days=1), midnight, "yesterday"),
        "this_week": (week, None, "this week"),
        "last_week": (week - timedelta(days=7), week, "last week"),
        "this_month": (month, None, "this month"),
        "last_month": (previous_month, month, "last month"),
        "last_n_days": (now - timedelta(days=days or RECENT_DAYS), None, f"over the past {days or RECENT_DAYS} days"),
    }
    return bounds.get(period, (None, None, ""))


def subjects_named(db: Session, topic: str) -> list[Subject]:
    """Subjects whose title or alias matches topic, ignoring case and plurals."""
    key = name_key(topic)
    if not key:
        return []
    matches = []
    for subject in db.scalars(select(Subject)).all():
        names = {name_key(name) for name in [subject.title, *subject.aliases]}
        if key in names or any(len(key) >= 4 and (key in name.split() or name in key.split()) for name in names):
            matches.append(subject)
    return matches


def subject_members(db: Session, subject_ids: list[UUID]) -> set[UUID]:
    """Concepts in subject_ids or any descendant subject."""
    pending, seen = list(subject_ids), set()
    while pending and len(seen) < 1000:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(db.scalars(select(Subject.id).where(Subject.parent_id == current)).all())
    return set(db.scalars(select(SubjectConcept.concept_id).where(SubjectConcept.subject_id.in_(seen))).all()) if seen else set()


def conversation_concepts(db: Session, conversation_id: UUID) -> list[UUID]:
    """Concepts discussed in this conversation, most recent first."""
    rows = db.execute(select(CaptureConcept.concept_id, func.max(Capture.created_at).label("at"))
        .join(Capture, Capture.id == CaptureConcept.capture_id)
        .where(Capture.conversation_id == conversation_id, Capture.status != "archived")
        .group_by(CaptureConcept.concept_id).order_by(func.max(Capture.created_at).desc()).limit(MAX_SCOPE)).all()
    return [row.concept_id for row in rows]


def resolve(db: Session, *, topic: str | None, refers_to_context: bool, period: str, days: int | None,
            timezone_name: str, conversation_id: UUID | None, context_ids: list[UUID] | None = None,
            topic_vector: tuple[list[float], str] | None = None, limit: int = MAX_SCOPE) -> Scope:
    """Resolve conversational scope to active concepts with a current saved explanation.

    topic is the user's wording; refers_to_context marks "this/it"; period/days/timezone_name
    bound when the explanation was saved; context_ids are concepts the current turn or the
    last activity just used; topic_vector is a precomputed (query vector, profile key).
    """
    since, until, phrase = period_bounds(period, days, timezone_name)
    scope = Scope(topic=topic, since=since, until=until, period_phrase=phrase)
    candidates: list[UUID] = []
    if topic:
        scope.basis = "topic"
        subjects = subjects_named(db, topic)
        scope.subject_ids = [s.id for s in subjects]
        if len(subjects) == 1:
            scope.topic = subjects[0].title
        candidates.extend(subject_members(db, scope.subject_ids))
        candidates.extend(hit.id for hit in text_search(db, topic, 50) if hit.type == "concept")
        if topic_vector is not None:
            hits = [hit for hit in vector_search(db, topic_vector[0], topic_vector[1], 30) if hit.similarity is not None]
            best = max((hit.similarity for hit in hits), default=0)
            candidates.extend(hit.id for hit in hits if hit.similarity >= max(TOPIC_MINIMUM, best - TOPIC_MARGIN))
    elif context_ids:
        scope.basis = "context"
        candidates.extend(context_ids)
    elif refers_to_context and conversation_id:
        scope.basis = "context"
        conversation = db.get(Conversation, conversation_id)
        candidates.extend(conversation_concepts(db, conversation_id))
        if conversation and conversation.subject_id:
            candidates.extend(subject_members(db, [conversation.subject_id]))
            scope.subject_ids = [conversation.subject_id]
    else:
        scope.basis = "bank"
        candidates = None  # Every active concept, bounded below by date and recency.
    scope.concept_ids, scope.considered = eligible(db, candidates, since, until, limit)
    return scope


def eligible(db: Session, candidates: list[UUID] | None, since, until, limit: int) -> tuple[list[UUID], int]:
    """Keep active concepts whose current explanation exists and, with a period, that the user
    explained or revised inside it; order by most recent saved explanation."""
    latest = latest_revisions()
    current = select(Concept.id, ExplanationRevision.created_at.label("current_at")).join(
        latest, latest.c.concept_id == Concept.id).join(ExplanationRevision, and_(
        ExplanationRevision.concept_id == Concept.id, ExplanationRevision.revision_number == latest.c.number)).where(
        Concept.archived_at.is_(None))
    if candidates is not None:
        if not candidates:
            return [], 0
        current = current.where(Concept.id.in_(set(candidates)))
    if since or until:
        window = select(ExplanationRevision.concept_id).where(ExplanationRevision.retracted_at.is_(None))
        if since:
            window = window.where(ExplanationRevision.created_at >= since)
        if until:
            window = window.where(ExplanationRevision.created_at < until)
        current = current.where(Concept.id.in_(window))
    rows = db.execute(current.order_by(ExplanationRevision.created_at.desc(), Concept.id)).all()
    if candidates is not None:
        # Preserve the caller's relevance order (subject/text/semantic/context) within the window.
        rank = {concept_id: index for index, concept_id in enumerate(dict.fromkeys(candidates))}
        rows = sorted(rows, key=lambda row: rank.get(row.id, len(rank)))
    return [row.id for row in rows[:limit]], len(rows)
