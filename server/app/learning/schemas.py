"""Generated teaching material is distinct from banked user understanding."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["clarification", "suggestions", "fact_check", "lesson", "worked_example", "diagram"]
    concept_ids: list[UUID] = Field(min_length=1, max_length=20)
    resource_ids: list[UUID] = Field(default_factory=list, max_length=10)
    question: str = Field(default="", max_length=4000)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: UUID
    quote: str = Field(min_length=1, max_length=1200)


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["correction", "gap", "relationship"]
    concept_id: UUID
    rationale: str = Field(min_length=1, max_length=4000)
    explanation_text: str | None = Field(default=None, max_length=20000)
    target_concept_id: UUID | None = None
    relation_type: Literal["related_to", "prerequisite_of", "part_of", "applies_to"] | None = None
    evidence: Literal["unrecorded", "uncertain", "source_supported"] = "uncertain"
    diagnostic_question: str | None = Field(default=None, max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def valid_kind(self):
        if self.kind == "correction" and not self.explanation_text:
            raise ValueError("A correction needs proposed explanation text")
        if self.kind == "relationship" and (not self.target_concept_id or not self.relation_type):
            raise ValueError("A relationship needs a target and type")
        if self.kind == "gap" and (not self.diagnostic_question or self.evidence == "source_supported"):
            raise ValueError("An unestablished gap needs a diagnostic question")
        if self.evidence == "source_supported" and not self.citations:
            raise ValueError("Source-supported suggestions require citations")
        return self


class LearningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=30000)
    optional_questions: list[str] = Field(default_factory=list, max_length=5)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=10)
    verification: Literal["not_verified", "sources_compared"] = "not_verified"
    uncertainty: list[str] = Field(default_factory=list, max_length=20)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["adopt", "dismiss"]
    message: str = Field(min_length=1, max_length=4000)


class TaskReceipt(BaseModel):
    artifact_id: UUID
    job_id: UUID


class SuggestionRead(BaseModel):
    id: UUID
    payload: Suggestion
    status: Literal["pending", "adopted", "dismissed"]
    applied_revision_id: UUID | None
    decision_note: str | None


class ArtifactRead(BaseModel):
    id: UUID
    kind: str
    inputs: dict
    output: LearningOutput | None
    model_key: str | None
    prompt_version: str | None
    suggestions: list[SuggestionRead]


class DecisionRead(BaseModel):
    id: UUID
    status: Literal["adopted", "dismissed"]
    revision_id: UUID | None
