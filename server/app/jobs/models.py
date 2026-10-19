"""PostgreSQL work records and immutable embedding profile descriptions."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint("kind IN ('capture', 'embedding', 'review_feedback')", name="work_kind_valid"),
        CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name="work_status_valid"),
        CheckConstraint("(kind = 'capture' AND capture_id IS NOT NULL AND revision_id IS NULL AND attempt_id IS NULL) OR "
                        "(kind = 'embedding' AND revision_id IS NOT NULL AND capture_id IS NULL AND attempt_id IS NULL) OR "
                        "(kind = 'review_feedback' AND attempt_id IS NOT NULL AND capture_id IS NULL AND revision_id IS NULL)", name="work_target_valid"),
        Index("ix_work_items_schedule", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dedup_key: Mapped[str] = mapped_column(String(400), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id", ondelete="CASCADE"), nullable=True, index=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("explanation_revisions.id", ondelete="CASCADE"), nullable=True, index=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("review_attempts.id", ondelete="CASCADE"), nullable=True, index=True)
    profile_key: Mapped[str | None] = mapped_column(String(255), ForeignKey("embedding_profiles.key"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
