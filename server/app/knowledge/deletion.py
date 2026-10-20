"""Conservative permanent deletion: archive first, preserve referenced history."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from typing import Annotated
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.captures.models import AIProposal, Capture
from app.database import get_db
from app.errors import Conflict, NotFound
from app.knowledge.models import Concept, Resource
from app.learning.models import LearningArtifact
from app.models import Base

router = APIRouter(prefix="/api/v1", tags=["permanent deletion"])
Db = Annotated[Session, Depends(get_db)]


def delete_unreferenced(db, model, item_id):
    with db.begin():
        item = db.scalar(select(model).where(model.id == item_id).with_for_update())
        if item is None:
            raise NotFound("Record not found")
        archived = item.status == "archived" if model is Capture else bool(item.archived_at)
        if not archived:
            raise Conflict("Archive this record before permanently deleting it")
        table = model.__table__
        # Refuse any relational reference, including cascades that would otherwise
        # remove explanation, review, source or subject records implicitly.
        for candidate in Base.metadata.tables.values():
            for fk in candidate.foreign_keys:
                if fk.column.table is table and db.scalar(select(exists().where(fk.parent == item_id))):
                    raise Conflict("This record is referenced by saved history; retain it archived")
        # Learning tasks also carry immutable IDs inside their context snapshots.
        for artifact in db.scalars(select(LearningArtifact)).all():
            import json
            if str(item_id) in json.dumps(artifact.inputs) or str(item_id) in json.dumps(artifact.output):
                raise Conflict("A learning artifact references this record; retain it archived")
        db.delete(item)


@router.delete("/concepts/{concept_id}", status_code=204)
def delete_concept(concept_id: UUID, db: Db):
    delete_unreferenced(db, Concept, concept_id)
    return Response(status_code=204)


@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: UUID, db: Db):
    delete_unreferenced(db, Resource, resource_id)
    return Response(status_code=204)


@router.delete("/captures/{capture_id}", status_code=204)
def delete_capture(capture_id: UUID, db: Db):
    delete_unreferenced(db, Capture, capture_id)
    return Response(status_code=204)
