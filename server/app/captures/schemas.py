"""HTTP shapes for raw captures and AI formatting candidates."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CaptureStatus = Literal["pending", "processed", "archived"]
ProposalKind = Literal["formatting", "correction", "gap", "relationship", "clarification", "resource"]


class CaptureCreate(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)
    input_kind: Literal["text", "voice_transcript"] = "text"

    @field_validator("raw_text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_text must not be blank")
        return value


class CaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    raw_text: str
    input_kind: str
    status: CaptureStatus
    created_at: datetime
    conversation_id: UUID | None = None
    reply_to_proposal_id: UUID | None = None


class CapturePage(BaseModel):
    items: list[CaptureRead]
    next_cursor: str | None


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    capture_id: UUID
    kind: ProposalKind
    payload: dict[str, Any]
    model_key: str
    prompt_version: str | None = None
    application_mode: Literal["automatic", "user"] | None = None
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    reviewed_at: datetime | None


class ProposalPage(BaseModel):
    items: list[ProposalRead]
    next_cursor: str | None


class CaptureDetail(CaptureRead):
    concept_ids: list[UUID]
    proposals: list[ProposalRead]


class BankCapture(BaseModel):
    explanation_text: str = Field(min_length=1)
    concept_id: UUID | None = None
    new_title: str | None = Field(default=None, min_length=1, max_length=255)
    formatting_proposal_id: UUID | None = None

    @field_validator("explanation_text", "new_title")
    @classmethod
    def nonblank_value(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "BankCapture":
        if (self.concept_id is None) == (self.new_title is None):
            raise ValueError("Supply exactly one of concept_id or new_title")
        return self


class BankResult(BaseModel):
    concept_id: UUID
    revision_id: UUID
    origin: Literal["user_written", "ai_formatted_user_input", "user_edited_format"]
    embedding_status: Literal["not_configured", "pending"]


class QuickCapture(CaptureCreate):
    conversation_id: UUID | None = None
    request_id: UUID | None = None
    reply_to_proposal_id: UUID | None = None


class CaptureReceipt(BaseModel):
    capture_id: UUID
    conversation_id: UUID
    processing_job_id: UUID
    resource_ids: list[UUID]
    saved: bool = True
    message: str = "Saved"


class ConversationRead(BaseModel):
    id: UUID
    title: str | None
    captures: list[CaptureRead]
    next_cursor: str | None
