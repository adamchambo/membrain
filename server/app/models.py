"""Import every mapped class so Alembic sees the full metadata graph."""

from app.db.base import Base
from app.jobs.models import EmbeddingProfile, WorkItem
from app.captures.models import AIProposal, Capture, Conversation
from app.knowledge.models import (
    CaptureConcept,
    Concept,
    ConceptEmbedding,
    ConceptRelationship,
    ConceptResource,
    ExplanationRevision,
    Resource,
)
from app.review.models import ReviewAttempt, ReviewAttemptConcept, ReviewQuestion, ReviewScopeConcept, ReviewSession
from app.setup.models import BankSettings, ProfileMigration, WorkerHeartbeat
from app.resources.models import SourceVersion, SourceChunk
from app.learning.models import Subject, SubjectConcept, LearningArtifact, LearningSuggestion
from app.portability.models import ImportBatch

__all__ = [
    "Base", "Capture", "AIProposal", "Concept", "CaptureConcept",
    "ExplanationRevision", "Resource", "ConceptResource", "ConceptRelationship",
    "ConceptEmbedding", "ReviewSession", "ReviewScopeConcept", "ReviewAttempt",
    "ReviewAttemptConcept",
    "Conversation", "EmbeddingProfile", "WorkItem", "ReviewQuestion",
    "BankSettings", "ProfileMigration", "WorkerHeartbeat", "SourceVersion", "SourceChunk",
    "Subject", "SubjectConcept", "LearningArtifact", "LearningSuggestion", "ImportBatch",
]
