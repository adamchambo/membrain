"""Client-owned session types shared by real and stub backends."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from uuid import UUID


class ClientError(Exception):
    """A safe, user-readable error, without raw provider or credential payloads."""


@dataclass(frozen=True)
class Context:
    conversation_id: UUID | None = None
    capture_id: UUID | None = None
    concept_id: UUID | None = None
    resource_id: UUID | None = None
    subject_id: UUID | None = None
    concept_ids: tuple[UUID, ...] = ()
    review_session_id: UUID | None = None
    question_id: UUID | None = None
    attempt_id: UUID | None = None
    artifact_id: UUID | None = None
    suggestion_id: UUID | None = None
    proposal_id: UUID | None = None
    job_id: UUID | None = None
    request_id: UUID | None = None
    mode: str = 'cue_card'
    label: str = ''
    item_kind: str = 'concept'
    diagnostic_question: str = ''
    question: str = ''
    since: str = ''
    until: str = ''
    search_mode: str = 'hybrid'
    membership_subject_id: UUID | None = None
    reflection_concept_ids: tuple[UUID, ...] = ()

    def scope(self, *, concept: UUID | None = None, subject: UUID | None = None,
              label: str = '') -> Context:
        """Select concept or subject, clearing stale scope-dependent activity IDs."""
        return replace(self, concept_id=concept, subject_id=subject,
                       concept_ids=(concept,) if concept else (), label=label,
                       resource_id=None, item_kind='subject' if subject else 'concept',
                       review_session_id=None, question_id=None, attempt_id=None,
                       artifact_id=None, suggestion_id=None, diagnostic_question='', question='')


@dataclass(frozen=True)
class Item:
    id: UUID
    kind: str
    title: str
    detail: str = ''


@dataclass(frozen=True)
class Job:
    id: UUID
    kind: str
    target: UUID | None = None
    status: str = 'pending'


@dataclass(frozen=True)
class Result:
    message: str
    context: Context
    items: tuple[Item, ...] = ()
    payload: Any = None
    cursor: str | None = None
    job: Job | None = None
    prompt: str | None = None


class Backend(Protocol):
    is_stub: bool
    def call(self, operation: str, text: str, context: Context, *, cursor: str | None = None) -> Result: ...
    def poll(self, job: Job, context: Context) -> tuple[str, Result]: ...
    def close(self) -> None: ...
