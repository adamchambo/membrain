"""Typed subject, review history, and reflection HTTP responses."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel
from app.review.schemas import AttemptRead


class SubjectRead(BaseModel):
    id: UUID
    title: str
    parent_id: UUID | None


class SubjectList(BaseModel):
    items: list[SubjectRead]


class MembershipRead(BaseModel):
    subject_id: UUID
    concept_id: UUID


class SubjectScopeRead(BaseModel):
    subject_id: UUID
    concept_ids: list[UUID]
    includes_descendants: bool


class ReviewHistoryItem(BaseModel):
    id: UUID
    mode: str
    requested_scope: str
    started_at: datetime
    finished_at: datetime | None


class ReviewHistory(BaseModel):
    items: list[ReviewHistoryItem]


class ReviewSelection(BaseModel):
    policy: str
    last_attempt_id: UUID | None
    recall: str
    mastery: Literal["not_inferred"]


class ReviewSnapshot(BaseModel):
    concept_id: UUID
    title: str
    revision_id: UUID
    explanation: str
    mode: str
    selection: ReviewSelection


class SessionQuestionRead(BaseModel):
    id: UUID
    concept_id: UUID
    prompt: str
    snapshot: ReviewSnapshot


class SessionDetail(BaseModel):
    id: UUID
    mode: str
    finished_at: datetime | None
    questions: list[SessionQuestionRead]
    attempts: list[AttemptRead]


class ReflectionRevision(BaseModel):
    id: UUID
    concept_id: UUID
    origin: str
    retracted_at: datetime | None


class ReflectionRead(BaseModel):
    eligible_concept_ids: list[UUID]
    reviewed_concept_ids: list[UUID]
    unreviewed_concept_ids: list[UUID]
    revisions: list[ReflectionRevision]
    attempts: list[AttemptRead]
    truncated: bool
    mastery: Literal["not_inferred"]
