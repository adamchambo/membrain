"""Persistent learning needs and the bank-wide ranking used to pick one.

Ranking is deterministic so every saved concept is considered without sending the
whole bank to the model; the model only chooses among the top candidates and explains.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.discovery.service import latest_revisions
from app.knowledge.models import Concept, ExplanationRevision
from app.learning.models import LearningNeed, LearningNeedEvent
from app.review.models import ReviewAttempt, ReviewAttemptConcept

EVIDENCE_WEIGHT = {"model_suspected": 1, "user_uncertain": 2, "observed_in_answer": 3}
# "kind of like" and "sort of" usually introduce an analogy, so they are not counted as doubt.
HEDGE = re.compile(r"\b(i think|i guess|maybe|perhaps|probably|not sure|unsure|i don'?t (know|understand|get)|confus\w*"
                   r"|i believe|might be|no idea|i wonder)\b|\?", re.I)
WEAK_RECALL = {"partial", "different", "unclear"}
WEAK_FACTUAL = {"incorrect", "partially_correct"}


def record(db: Session, *, concept_id: UUID, kind: str, summary: str, evidence: str, event: str, turn_id: UUID | None,
           payload: dict, excerpt: str | None = None, revision_id: UUID | None = None, artifact_id: UUID | None = None) -> LearningNeed:
    """Add evidence to the open need of this kind for concept_id, or open one.

    Evidence only strengthens (suspected < stated uncertainty < observed in an answer);
    the event log keeps every observation, including ones that did not change status.
    """
    need = db.scalar(select(LearningNeed).where(LearningNeed.concept_id == concept_id, LearningNeed.kind == kind,
                     LearningNeed.status.in_(["open", "exploring"])).order_by(LearningNeed.created_at.desc()).limit(1))
    now = datetime.now(timezone.utc)
    if need is None:
        need = LearningNeed(concept_id=concept_id, kind=kind, summary=summary, evidence=evidence, status="open",
                            user_excerpt=excerpt, revision_id=revision_id, artifact_id=artifact_id)
        db.add(need)
        db.flush()
    else:
        if EVIDENCE_WEIGHT[evidence] > EVIDENCE_WEIGHT[need.evidence]:
            need.evidence = evidence
        need.updated_at = now
        if excerpt and not need.user_excerpt:
            need.user_excerpt, need.revision_id = excerpt, revision_id
    db.add(LearningNeedEvent(need_id=need.id, kind=event, turn_id=turn_id, payload=payload))
    return need


def feedback_signals(text: str | None) -> tuple[str | None, str | None]:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return None, None
    return value.get("recall"), value.get("factual")


def rank(db: Session, now: datetime | None = None, limit: int = 4) -> tuple[list[dict], int]:
    """Score every active concept for "pick a gap"; returns (top candidates with reasons, considered).

    Signals: open needs by evidence strength, the user's own hedging, weak recent answers,
    never practised, and staleness. A diagnostic asked in the last two days is penalised so
    repeated requests move on. Absence of evidence never adds a "gap" by itself.
    """
    now = now or datetime.now(timezone.utc)
    latest = latest_revisions()
    rows = db.execute(select(Concept.id, Concept.title, ExplanationRevision.id.label("revision_id"), ExplanationRevision.body,
        ExplanationRevision.created_at).join(latest, latest.c.concept_id == Concept.id).join(ExplanationRevision, and_(
        ExplanationRevision.concept_id == Concept.id, ExplanationRevision.revision_number == latest.c.number))
        .where(Concept.archived_at.is_(None))).all()
    needs: dict[UUID, list[LearningNeed]] = {}
    for need in db.scalars(select(LearningNeed).where(LearningNeed.status.in_(["open", "exploring"]))).all():
        needs.setdefault(need.concept_id, []).append(need)
    asked = dict(db.execute(select(LearningNeed.concept_id, func.max(LearningNeedEvent.created_at))
        .join(LearningNeedEvent, LearningNeedEvent.need_id == LearningNeed.id).where(LearningNeedEvent.kind == "asked")
        .group_by(LearningNeed.concept_id)).all())
    last_attempt: dict[UUID, tuple[datetime, str | None]] = {}
    for concept_id, answered_at, feedback in db.execute(select(ReviewAttemptConcept.concept_id, ReviewAttempt.answered_at,
            ReviewAttempt.feedback).join(ReviewAttempt, ReviewAttempt.id == ReviewAttemptConcept.review_attempt_id)
            .order_by(ReviewAttempt.answered_at.desc())).all():
        last_attempt.setdefault(concept_id, (answered_at, feedback))
    scored = []
    for row in rows:
        score, reasons = 0.0, []
        concept_needs = needs.get(row.id, [])
        if concept_needs:
            strongest = max(concept_needs, key=lambda n: EVIDENCE_WEIGHT[n.evidence])
            score += 1 + EVIDENCE_WEIGHT[strongest.evidence]
            reasons.append(f"open {strongest.kind} ({strongest.evidence.replace('_', ' ')}): {strongest.summary[:160]}")
        if HEDGE.search(row.body):
            score += 2
            reasons.append("your saved explanation expresses uncertainty")
        attempt = last_attempt.get(row.id)
        if attempt is None:
            score += 1
            reasons.append("never practised")
        else:
            recall, factual = feedback_signals(attempt[1])
            if recall in WEAK_RECALL or factual in WEAK_FACTUAL:
                score += 2
                reasons.append("your last answer about it was incomplete or incorrect")
        touched = max(row.created_at, attempt[0]) if attempt else row.created_at
        age_days = (now - touched).total_seconds() / 86400
        if age_days > 14:
            score += min(1.5, age_days / 30)
            reasons.append(f"not revisited for {int(age_days)} days")
        if row.id in asked and now - asked[row.id] < timedelta(days=2):
            score -= 3
        scored.append({"concept_id": row.id, "title": row.title, "revision_id": row.revision_id, "score": round(score, 2),
                       "reasons": reasons})
    scored.sort(key=lambda item: (-item["score"], item["title"].casefold(), str(item["concept_id"])))
    return scored[:limit], len(rows)
