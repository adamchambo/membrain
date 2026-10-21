"""Model output contracts for conversational activities; every output is untrusted."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def optional_text(value):
    return None if isinstance(value, str) and value.strip().casefold() in {"", "none", "null", "n/a"} else value


class RecallOutput(Output):
    reminder: str = Field(min_length=1, max_length=3000)
    holds: list[str] = Field(default_factory=list, max_length=4)
    breaks_down: list[str] = Field(default_factory=list, max_length=4)
    assessment: Literal["accurate", "partly_accurate", "inaccurate", "unresolved"]
    issue_excerpt: str | None = Field(default=None, max_length=2000)

    _blank = field_validator("issue_excerpt", mode="before")(optional_text)


class TeachOutput(Output):
    content: str = Field(min_length=1, max_length=8000)
    summary: str = Field(min_length=1, max_length=1500)
    check_question: str | None = Field(default=None, max_length=500)

    _blank = field_validator("check_question", mode="before")(optional_text)


class Finding(Output):
    concept_id: UUID
    kind: Literal["gap", "misconception"]
    summary: str = Field(min_length=1, max_length=600)
    why: str = Field(min_length=1, max_length=1500)
    user_excerpt: str | None = Field(default=None, max_length=2000)
    confidence: Literal["low", "medium", "high"] = "low"

    _blank = field_validator("user_excerpt", mode="before")(optional_text)


class DiagnosticQuestion(Output):
    concept_id: UUID
    text: str = Field(min_length=1, max_length=800)


class DiagnoseOutput(Output):
    findings: list[Finding] = Field(default_factory=list, max_length=3)
    question: DiagnosticQuestion
    reason: str = Field(default="", max_length=600)


class OpenQuestionOutput(Output):
    question: str = Field(min_length=1, max_length=800)


class MultipleChoiceOutput(Output):
    question: str = Field(min_length=1, max_length=800)
    options: list[str] = Field(min_length=3, max_length=5)
    correct_index: int = Field(ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=1500)

    @field_validator("options")
    @classmethod
    def distinct(cls, values):
        values = [value.strip() for value in values]
        if any(not value for value in values) or len({value.casefold() for value in values}) != len(values):
            raise ValueError("Options must be distinct and nonblank")
        return values

    @model_validator(mode="after")
    def key_in_range(self):
        if self.correct_index >= len(self.options):
            raise ValueError("correct_index must refer to an option")
        return self


class BlindAnswer(Output):
    index: int = Field(ge=0, le=4)


class AnswerAssessment(Output):
    chosen_index: int | None = Field(default=None, ge=0, le=4)
    recall: Literal["consistent", "partial", "different", "unclear", "not_applicable"]
    factual: Literal["correct", "partially_correct", "incorrect", "unresolved"]
    feedback: str = Field(min_length=1, max_length=2000)
    saved_conflict: str | None = Field(default=None, max_length=1000)

    _blank = field_validator("saved_conflict", mode="before")(optional_text)


class DiagnosticAssessment(Output):
    outcome: Literal["difficulty_observed", "improvement_observed", "inconclusive"]
    feedback: str = Field(min_length=1, max_length=2000)
