from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.resources import service
from app.resources.schemas import ChunkPage, SourceReceipt

router = APIRouter(prefix="/api/v1/resources", tags=["source content"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/{resource_id}/content", status_code=202, response_model=SourceReceipt)
def upload_source(resource_id: UUID, data: service.SourceUpload, db: Db):
    """Import UTF-8 TXT, Markdown or HTML. URL bookmarks never trigger a fetch."""
    return service.upload(db, resource_id, data)


@router.get("/{resource_id}/chunks", response_model=ChunkPage)
def source_chunks(resource_id: UUID, db: Db, query: str | None = Query(default=None, min_length=1, max_length=500), limit: int = Query(default=25, ge=1, le=100)):
    return service.chunks(db, resource_id, query, limit)
