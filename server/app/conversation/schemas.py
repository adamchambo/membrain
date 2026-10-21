"""HTTP shapes for conversational turns."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000, description="The user's message, saved verbatim.")
    client_message_id: UUID = Field(description="Client-generated retry key; resubmitting it returns the same turn.")
    conversation_id: UUID | None = Field(default=None, description="Existing conversation, or omitted to start one.")
    timezone: str = Field(default="UTC", max_length=64, description="IANA timezone used to interpret dates such as 'last week'.")
    input_kind: Literal["text", "voice_transcript"] = "text"

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class ProgressRead(BaseModel):
    at: datetime
    text: str


class ActiveQuestion(BaseModel):
    """The question awaiting an answer; multiple-choice keys are never included."""
    type: Literal["practice", "diagnostic"]
    format: str | None = None
    question: str
    options: list[str] = Field(default_factory=list)
    number: int | None = None
    target: int | None = None


class TurnRead(BaseModel):
    id: UUID
    conversation_id: UUID
    capture_id: UUID
    sequence: int
    message: str
    status: Literal["processing", "completed", "failed"]
    progress: list[ProgressRead]
    reply: str | None
    error: str | None
    job_id: UUID | None
    banked_concept_ids: list[UUID] = Field(description="Concepts whose saved explanation this turn created or updated.")
    active_question: ActiveQuestion | None = Field(description="The conversation's current question, if any, at read time.")
    created_at: datetime
    completed_at: datetime | None


class TurnPage(BaseModel):
    items: list[TurnRead]
    next_before: int | None = Field(description="Pass as before to load older turns.")
