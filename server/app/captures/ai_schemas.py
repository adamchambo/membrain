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


def blank_names(values: list[str]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


class Understanding(TaskOutput):
    title: str = Field(min_length=1, max_length=255)
    explanation_text: str = Field(min_length=1, max_length=20000)
    source_excerpts: list[str] = Field(min_length=1, max_length=10)
    uncertainty: list[str] = Field(default_factory=list, max_length=20)
    existing_concept_id: UUID | None = None
    subjects: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("source_excerpts")
    @classmethod
    def nonblank_sources(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Source excerpts must contain text")
        return values

    @field_validator("subjects", mode="before")
    @classmethod
    def subject_names(cls, values):
        return [value[:120] for value in blank_names(values or [])][:3]


class Clarification(TaskOutput):
    question: str = Field(min_length=1, max_length=1000)
    source_excerpt: str = Field(min_length=1, max_length=20000)


class SubjectProposal(TaskOutput):
    title: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("aliases", mode="before")
    @classmethod
    def alias_names(cls, values):
        return [value[:120] for value in blank_names(values or [])][:5]


class CaptureOutput(TaskOutput):
    schema_version: Literal["capture.v1", "capture.v2"]
    topic_title: str | None = Field(default=None, min_length=1, max_length=255)
    topic_subject: SubjectProposal | None = None
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
