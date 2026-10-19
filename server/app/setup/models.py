import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BankSettings(Base):
    __tablename__ = "bank_settings"
    key: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    active_profile_key: Mapped[str | None] = mapped_column(String(255), ForeignKey("embedding_profiles.key"), nullable=True)


class ProfileMigration(Base):
    __tablename__ = "profile_migrations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_profile_key: Mapped[str] = mapped_column(String(255), ForeignKey("embedding_profiles.key"), nullable=False)
    source_profile_key: Mapped[str | None] = mapped_column(String(255), ForeignKey("embedding_profiles.key"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
