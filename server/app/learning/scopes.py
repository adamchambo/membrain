"""Inspectable subject membership rather than guessing scope from its label."""

from uuid import UUID

from sqlalchemy import select

from app.errors import Conflict, NotFound
from app.knowledge.models import Concept
from app.learning.models import Subject, SubjectConcept


def resolve_subject(db, subject_id: UUID) -> list[UUID]:
    if db.get(Subject, subject_id) is None:
        raise NotFound("Subject not found")
    descendants, todo = set(), [subject_id]
    while todo:
        current = todo.pop()
        if current in descendants:
            continue
        descendants.add(current)
        todo.extend(db.scalars(select(Subject.id).where(Subject.parent_id == current)).all())
        if len(descendants) > 1000:
            raise Conflict("Subject hierarchy is too large; choose a narrower scope")
    return list(db.scalars(select(SubjectConcept.concept_id).join(Concept, Concept.id == SubjectConcept.concept_id)
        .where(SubjectConcept.subject_id.in_(descendants), Concept.archived_at.is_(None)).distinct()
        .order_by(SubjectConcept.concept_id)).all())
