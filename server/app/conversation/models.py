"""One user message and Membrain's reply, processed durably in order."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationTurn(Base):
    """The user's words stay in their capture; this row holds interpretation and reply.

    progress is an append-only list of user-visible steps, so a reconnecting client can
    replay what happened. effects records each completed intent by index; a retried job
    skips those, so durable writes happen at most once.
    """

    __tablename__ = "conversation_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence", name="uq_turn_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True)
    capture_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("captures.id"), nullable=False, unique=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    intents: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    progress: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    effects: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
