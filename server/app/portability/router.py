from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.portability.service import export_bank, import_bank

router = APIRouter(prefix="/api/v1/bank", tags=["portability"])
Db = Annotated[Session, Depends(get_db)]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    document: dict = Field(description="Versioned portable bank document, validated by the import service.")
    preview: bool = True


class BankDocument(BaseModel):
    format: str
    tables: dict[str, list[dict]] = Field(description="Versioned storage records keyed by table name; intentionally extensible JSON rows.")
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
