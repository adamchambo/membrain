from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.portability.service import export_bank, import_bank
from app.setup.router import require_admin

router = APIRouter(prefix="/api/v1/bank", tags=["portability"], dependencies=[Depends(require_admin)])
Db = Annotated[Session, Depends(get_db)]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    document: dict
    preview: bool = True


class BankDocument(BaseModel):
    format: str
    tables: dict[str, list[dict]]
    excluded: list[str]


class ImportRead(BaseModel):
    valid: bool
    counts: dict[str, int]
    policy: str
    writes: bool
    id_map: dict[str, UUID] | None = None


@router.get("/export", response_model=BankDocument)
def export(db: Db):
    return export_bank(db)


@router.post("/import", response_model=ImportRead)
def import_data(data: ImportRequest, db: Db):
    return import_bank(db, data.document, data.request_id, data.preview)
