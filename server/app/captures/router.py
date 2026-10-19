"""Capture and formatting HTTP routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.formatter import Formatter, get_formatter
from app.captures import service
from app.captures.schemas import (
    BankCapture, BankResult, CaptureCreate, CaptureDetail, CapturePage,
    CaptureRead, CaptureStatus, ProposalKind, ProposalPage, ProposalRead,
)
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["captures"])
Db = Annotated[Session, Depends(get_db)]


@router.post("/captures", response_model=CaptureRead, status_code=201)
def create_capture(data: CaptureCreate, db: Db):
    return service.create_capture(db, data)


@router.get("/captures", response_model=CapturePage)
def list_captures(db: Db, status: CaptureStatus | None = None, cursor: str | None = None,
                  limit: Annotated[int, Query(ge=1, le=100)] = 25):
    items, next_cursor = service.list_captures(db, status, cursor, limit)
    return CapturePage(items=items, next_cursor=next_cursor)


@router.get("/captures/{capture_id}", response_model=CaptureDetail)
def get_capture(capture_id: UUID, db: Db):
    capture, concept_ids, proposals = service.get_capture(db, capture_id)
    return CaptureDetail(**CaptureRead.model_validate(capture).model_dump(), concept_ids=concept_ids, proposals=proposals)


@router.post("/captures/{capture_id}/format", response_model=ProposalRead, status_code=201)
def format_capture(capture_id: UUID, db: Db, formatter: Annotated[Formatter, Depends(get_formatter)]):
    return service.format_capture(db, capture_id, formatter)


@router.get("/captures/{capture_id}/proposals", response_model=ProposalPage)
def list_proposals(capture_id: UUID, db: Db, kind: ProposalKind | None = None,
                   cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 25):
    items, next_cursor = service.list_proposals(db, capture_id, kind, cursor, limit)
    return ProposalPage(items=items, next_cursor=next_cursor)


@router.post("/captures/{capture_id}/bank", response_model=BankResult, status_code=201)
def bank_capture(capture_id: UUID, data: BankCapture, db: Db):
    return service.bank_capture(db, capture_id, data)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalRead)
def reject_proposal(proposal_id: UUID, db: Db):
    return service.reject_proposal(db, proposal_id)
