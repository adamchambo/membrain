"""Raw learning captures and unapproved AI proposals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processed', 'archived')", name="capture_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True, index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True, nullable=True)
    reply_to_proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_proposals.id", use_alter=True, name="fk_capture_reply_proposal"), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIProposal(Base):
    __tablename__ = "ai_proposals"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="proposal_status_valid"),
        CheckConstraint(
            "kind IN ('formatting', 'correction', 'gap', 'relationship', 'clarification', 'resource')",
            name="proposal_kind_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capture_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id", ondelete="CASCADE"), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    model_key: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    application_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
