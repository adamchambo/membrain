"""Conversational capture, reversible banking, and durable AI work.

Revision ID: 20261019_01
Revises: 20261018_02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_01"
down_revision = "20261018_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("captures", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column("captures", sa.Column("request_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_captures_conversation", "captures", "conversations", ["conversation_id"], ["id"])
    op.create_index("ix_captures_conversation_id", "captures", ["conversation_id"])
    op.create_unique_constraint("uq_captures_request_id", "captures", ["request_id"])
    op.add_column("captures", sa.Column("reply_to_proposal_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_capture_reply_proposal", "captures", "ai_proposals", ["reply_to_proposal_id"], ["id"])
    op.add_column("ai_proposals", sa.Column("prompt_version", sa.String(64), nullable=True))
    op.add_column("ai_proposals", sa.Column("application_mode", sa.String(16), nullable=True))
    op.add_column("explanation_revisions", sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("resources", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_resources_capture_id", "resources", ["capture_id"])
    op.create_index("ix_concept_embeddings_model_key", "concept_embeddings", ["model_key"])
    op.create_table("embedding_profiles",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("work_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dedup_key", sa.String(400), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("capture_id", sa.UUID(), sa.ForeignKey("captures.id", ondelete="CASCADE"), nullable=True),
        sa.Column("revision_id", sa.UUID(), sa.ForeignKey("explanation_revisions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("profile_key", sa.String(255), sa.ForeignKey("embedding_profiles.key"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('capture', 'embedding')", name="work_kind_valid"),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name="work_status_valid"),
        sa.CheckConstraint("(kind = 'capture' AND capture_id IS NOT NULL AND revision_id IS NULL) OR "
                           "(kind = 'embedding' AND revision_id IS NOT NULL AND capture_id IS NULL)", name="work_target_valid"))
    op.create_index("ix_work_items_schedule", "work_items", ["status", "available_at"])
    op.create_index("ix_work_items_capture_id", "work_items", ["capture_id"])
    op.create_index("ix_work_items_revision_id", "work_items", ["revision_id"])


def downgrade():
    op.drop_table("work_items")
    op.drop_table("embedding_profiles")
    op.drop_index("ix_concept_embeddings_model_key", table_name="concept_embeddings")
    op.drop_index("ix_resources_capture_id", table_name="resources")
    op.drop_column("resources", "archived_at")
    op.drop_column("explanation_revisions", "retracted_at")
    op.drop_column("ai_proposals", "application_mode")
    op.drop_column("ai_proposals", "prompt_version")
    op.drop_constraint("fk_capture_reply_proposal", "captures", type_="foreignkey")
    op.drop_column("captures", "reply_to_proposal_id")
    op.drop_constraint("uq_captures_request_id", "captures", type_="unique")
    op.drop_column("captures", "request_id")
    op.drop_index("ix_captures_conversation_id", table_name="captures")
    op.drop_constraint("fk_captures_conversation", "captures", type_="foreignkey")
    op.drop_column("captures", "conversation_id")
    op.drop_table("conversations")
