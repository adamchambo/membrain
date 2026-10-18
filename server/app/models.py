"""Import every mapped class so Alembic sees the full metadata graph."""

from app.db.base import Base
from app.captures.models import AIProposal, Capture
from app.knowledge.models import (
    CaptureConcept,
    Concept,
    ConceptEmbedding,
    ConceptRelationship,
    ConceptResource,
    ExplanationRevision,
    Resource,
)
from app.review.models import ReviewAttempt, ReviewAttemptConcept, ReviewScopeConcept, ReviewSession

__all__ = [
    "Base", "Capture", "AIProposal", "Concept", "CaptureConcept",
    "ExplanationRevision", "Resource", "ConceptResource", "ConceptRelationship",
    "ConceptEmbedding", "ReviewSession", "ReviewScopeConcept", "ReviewAttempt",
    "ReviewAttemptConcept",
]
