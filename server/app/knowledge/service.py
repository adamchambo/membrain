"""Knowledge retrieval and user-confirmed changes."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.captures.models import Capture
from app.errors import Conflict, NotFound
from app.knowledge.models import (
    CaptureConcept, Concept, ConceptRelationship, ConceptResource, ExplanationRevision, Resource,
)
from app.knowledge.schemas import (
    ConceptDetail, ConceptSummary, RelationshipCreate, ResourceCreate, ResourceDetail, RevisionCreate,
)
from app.pagination import before_cursor, encode_cursor


def require_concept(db: Session, concept_id: UUID) -> Concept:
    concept = db.get(Concept, concept_id)
    if concept is None:
        raise NotFound("Concept not found")
    return concept


def latest_revision(db: Session, concept_id: UUID):
    return db.scalar(select(ExplanationRevision).where(ExplanationRevision.concept_id == concept_id)
                     .order_by(ExplanationRevision.revision_number.desc()).limit(1))


def summary(db: Session, concept: Concept) -> ConceptSummary:
    return ConceptSummary(id=concept.id, title=concept.title, created_at=concept.created_at,
                          archived_at=concept.archived_at, latest_revision=latest_revision(db, concept.id))


def list_concepts(db: Session, cursor: str | None, limit: int, include_archived: bool):
    query = select(Concept)
    if not include_archived:
        query = query.where(Concept.archived_at.is_(None))
    if cursor:
        query = query.where(before_cursor(Concept.created_at, Concept.id, cursor))
    rows = db.scalars(query.order_by(Concept.created_at.desc(), Concept.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return [summary(db, row) for row in rows[:limit]], next_cursor


def get_concept(db: Session, concept_id: UUID) -> ConceptDetail:
    concept = require_concept(db, concept_id)
    resources = db.scalars(select(Resource).join(ConceptResource, Resource.id == ConceptResource.resource_id)
                           .where(ConceptResource.concept_id == concept_id).order_by(Resource.created_at.desc())).all()
    relationships = db.scalars(select(ConceptRelationship)
        .where((ConceptRelationship.source_concept_id == concept_id) | (ConceptRelationship.target_concept_id == concept_id))
        .order_by(ConceptRelationship.confirmed_at.desc())).all()
    return ConceptDetail(**summary(db, concept).model_dump(), resources=resources, relationships=relationships)


def list_revisions(db: Session, concept_id: UUID, cursor: str | None, limit: int):
    require_concept(db, concept_id)
    query = select(ExplanationRevision).where(ExplanationRevision.concept_id == concept_id)
    if cursor:
        query = query.where(before_cursor(ExplanationRevision.created_at, ExplanationRevision.id, cursor))
    rows = db.scalars(query.order_by(ExplanationRevision.created_at.desc(), ExplanationRevision.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def add_revision(db: Session, concept_id: UUID, data: RevisionCreate) -> ExplanationRevision:
    with db.begin():
        concept = db.scalar(select(Concept).where(Concept.id == concept_id).with_for_update())
        if concept is None:
            raise NotFound("Concept not found")
        if concept.archived_at is not None:
            raise Conflict("Archived concepts cannot receive revisions")
        if data.capture_id and db.get(Capture, data.capture_id) is None:
            raise NotFound("Capture not found")
        previous = latest_revision(db, concept_id)
        revision = ExplanationRevision(concept_id=concept_id, capture_id=data.capture_id,
            revision_number=(previous.revision_number if previous else 0) + 1,
            body=data.explanation_text, origin="user_written")
        db.add(revision)
        if data.capture_id and db.get(CaptureConcept, (data.capture_id, concept_id)) is None:
            db.add(CaptureConcept(capture_id=data.capture_id, concept_id=concept_id))
        db.flush()
    return revision


def create_resource(db: Session, data: ResourceCreate) -> Resource:
    with db.begin():
        resource = Resource(**data.model_dump())
        db.add(resource)
        db.flush()
    return resource


def get_resource(db: Session, resource_id: UUID) -> ResourceDetail:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise NotFound("Resource not found")
    ids = db.scalars(select(ConceptResource.concept_id).where(ConceptResource.resource_id == resource_id)).all()
    return ResourceDetail(id=resource.id, capture_id=resource.capture_id, kind=resource.kind, uri=resource.uri,
                          title=resource.title, note=resource.note, created_at=resource.created_at, concept_ids=ids)


def attach_resource(db: Session, concept_id: UUID, resource_id: UUID):
    with db.begin():
        require_concept(db, concept_id)
        if db.get(Resource, resource_id) is None:
            raise NotFound("Resource not found")
        if db.get(ConceptResource, (concept_id, resource_id)) is not None:
            raise Conflict("Resource is already attached")
        db.add(ConceptResource(concept_id=concept_id, resource_id=resource_id))


def detach_resource(db: Session, concept_id: UUID, resource_id: UUID):
    with db.begin():
        link = db.get(ConceptResource, (concept_id, resource_id))
        if link is None:
            raise NotFound("Resource link not found")
        db.delete(link)


def list_relationships(db: Session, concept_id: UUID, cursor: str | None, limit: int):
    require_concept(db, concept_id)
    query = select(ConceptRelationship).where(
        (ConceptRelationship.source_concept_id == concept_id) | (ConceptRelationship.target_concept_id == concept_id))
    if cursor:
        query = query.where(before_cursor(ConceptRelationship.confirmed_at, ConceptRelationship.id, cursor))
    rows = db.scalars(query.order_by(ConceptRelationship.confirmed_at.desc(), ConceptRelationship.id.desc()).limit(limit + 1)).all()
    next_cursor = encode_cursor(rows[limit - 1].confirmed_at, rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], next_cursor


def add_relationship(db: Session, concept_id: UUID, data: RelationshipCreate) -> ConceptRelationship:
    with db.begin():
        require_concept(db, concept_id)
        require_concept(db, data.target_concept_id)
        if concept_id == data.target_concept_id:
            raise Conflict("A concept cannot link to itself")
        existing = db.scalar(select(ConceptRelationship).where(
            ConceptRelationship.source_concept_id == concept_id,
            ConceptRelationship.target_concept_id == data.target_concept_id,
            ConceptRelationship.relation_type == data.relation_type))
        if existing:
            raise Conflict("Relationship already exists")
        relationship = ConceptRelationship(source_concept_id=concept_id, **data.model_dump())
        db.add(relationship)
        db.flush()
    return relationship
