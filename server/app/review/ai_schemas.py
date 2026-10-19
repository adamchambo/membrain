"""Review evaluates recall against a snapshot, with correctness unverified."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=4000)


class FeedbackOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    recall: Literal["consistent", "partial", "different", "unclear"]
    feedback: str = Field(min_length=1, max_length=5000)
    correctness: Literal["not_verified"]
    follow_up_question: str | None = Field(default=None, min_length=1, max_length=1000)
