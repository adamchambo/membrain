"""The first review contract supports an explicit concept scope and cue cards."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    concept_ids: list[UUID] = Field(min_length=1, max_length=20)
    mode: Literal["cue_card"] = "cue_card"

    @field_validator("concept_ids")
    @classmethod
    def unique_concepts(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Concept IDs must be unique")
        return value


class SessionRead(BaseModel):
    id: UUID
    mode: str
    concept_ids: list[UUID]


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    review_session_id: UUID
    concept_id: UUID
    revision_id: UUID
    prompt: str
    answered_at: datetime | None
    created_at: datetime


class AttemptCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question_id: UUID
    response: str = Field(min_length=1, max_length=20000)


class AttemptRead(BaseModel):
    id: UUID
    review_session_id: UUID
    question_id: UUID | None
    response: str
    feedback: dict[str, Any] | None
    feedback_job_id: UUID | None
