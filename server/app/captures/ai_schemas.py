"""Task outputs, distinct from HTTP requests and persisted ORM records."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FormatCandidate(TaskOutput):
    """The existing single-explanation format endpoint's contract."""

    candidate_title: str = Field(min_length=1, max_length=255)
    explanation_text: str = Field(min_length=1, max_length=20000)
    uncertainty: list[str] = Field(default_factory=list, max_length=20)


class Understanding(TaskOutput):
    title: str = Field(min_length=1, max_length=255)
    explanation_text: str = Field(min_length=1, max_length=20000)
    source_excerpts: list[str] = Field(min_length=1, max_length=10)
    uncertainty: list[str] = Field(default_factory=list, max_length=20)
    existing_concept_id: UUID | None = None

    @field_validator("source_excerpts")
    @classmethod
    def nonblank_sources(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Source excerpts must contain text")
        return values


class Clarification(TaskOutput):
    question: str = Field(min_length=1, max_length=1000)
    source_excerpt: str = Field(min_length=1, max_length=20000)


class CaptureOutput(TaskOutput):
    schema_version: Literal["capture.v1"]
    topic_title: str | None = Field(default=None, min_length=1, max_length=255)
    understandings: list[Understanding] = Field(default_factory=list, max_length=20)
    clarifications: list[Clarification] = Field(default_factory=list, max_length=5)
    answered_clarification_id: UUID | None = None

    @model_validator(mode="after")
    def unique_targets(self):
        targets = [str(x.existing_concept_id) if x.existing_concept_id else x.title.casefold()
                   for x in self.understandings]
        if len(set(targets)) != len(targets):
            raise ValueError("Combine statements about the same concept into one understanding")
        return self
