"""Automatic, reversible subject grouping; matching is by name and recorded aliases."""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.learning.models import Subject, SubjectConcept


def name_key(value: str) -> str:
    """Compare names ignoring case, punctuation and a plural "s" ("Fractions" == "fraction")."""
    words = re.sub(r"[^\w\s]", " ", value.casefold()).split()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word for word in words)


def subject_index(db: Session) -> dict[str, Subject]:
    """Map every subject title and alias key to its subject; earliest subject wins collisions."""
    index: dict[str, Subject] = {}
    for subject in db.scalars(select(Subject).order_by(Subject.created_at, Subject.id)).all():
        for name in [subject.title, *subject.aliases]:
            index.setdefault(name_key(name), subject)
    return index


def ensure_subject(db: Session, title: str, aliases: list[str] | None = None, index: dict | None = None) -> Subject:
    """Return the subject matching title or any alias, creating an automatic one otherwise."""
    index = subject_index(db) if index is None else index
    names = [title, *(aliases or [])]
    subject = next((index[name_key(name)] for name in names if name_key(name) in index), None)
    if subject is None:
        subject = Subject(title=title.strip()[:255], origin="automatic", aliases=[])
        db.add(subject)
        db.flush()
    known = {name_key(subject.title), *map(name_key, subject.aliases)}
    added = [name.strip()[:120] for name in names if name.strip() and name_key(name) not in known]
    if added:
        subject.aliases = [*subject.aliases, *dict.fromkeys(added)][:20]
    for name in names:
        index.setdefault(name_key(name), subject)
    return subject


def assign(db: Session, subject_id: UUID, concept_id: UUID, capture_id: UUID | None) -> None:
    """Add an automatic membership unless one already exists (user links are never replaced)."""
    db.execute(insert(SubjectConcept).values(subject_id=subject_id, concept_id=concept_id, origin="automatic",
                                             capture_id=capture_id).on_conflict_do_nothing())
