"""Concepts, explanation history, resources, relationships, and vectors."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaptureConcept(Base):
    __tablename__ = "capture_concepts"

    capture_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True)


class ExplanationRevision(Base):
    __tablename__ = "explanation_revisions"
    __table_args__ = (
        UniqueConstraint("concept_id", "revision_number", name="uq_explanation_revision_number"),
        CheckConstraint("revision_number > 0", name="explanation_revision_positive"),
        CheckConstraint(
            "origin IN ('user_written', 'ai_formatted_user_input', 'user_edited_format')",
            name="explanation_origin_valid",
        ),
        CheckConstraint(
            "origin = 'user_written' OR (capture_id IS NOT NULL AND proposal_id IS NOT NULL)",
            name="ai_formatted_provenance_required",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id", ondelete="RESTRICT"), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_proposals.id", ondelete="RESTRICT"), nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConceptResource(Base):
    __tablename__ = "concept_resources"

    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)


class ConceptRelationship(Base):
    __tablename__ = "concept_relationships"
    __table_args__ = (
        UniqueConstraint("source_concept_id", "target_concept_id", "relation_type", name="uq_concept_relationship"),
        CheckConstraint("source_concept_id <> target_concept_id", name="concept_relationship_distinct"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    target_concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConceptEmbedding(Base):
    __tablename__ = "concept_embeddings"
    __table_args__ = (
        UniqueConstraint("explanation_revision_id", "model_key", name="uq_concept_embedding_model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    explanation_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("explanation_revisions.id", ondelete="CASCADE"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
