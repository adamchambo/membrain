"""conversation turns, automatic organisation, learning needs and multiple choice

Revision ID: 20261021_01
Revises: 20261019_03
Create Date: 2026-10-21 22:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261021_01"
down_revision: Union[str, None] = "20261019_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = "'capture', 'embedding', 'review_feedback', 'profile_migration', 'resource_extract', 'learning'"
TARGETS = ("(kind = 'capture' AND capture_id IS NOT NULL AND revision_id IS NULL AND attempt_id IS NULL) OR "
           "(kind = 'embedding' AND revision_id IS NOT NULL AND capture_id IS NULL AND attempt_id IS NULL) OR "
           "(kind = 'review_feedback' AND attempt_id IS NOT NULL AND capture_id IS NULL AND revision_id IS NULL) OR "
           "(kind IN ({}) AND capture_id IS NULL AND revision_id IS NULL AND attempt_id IS NULL)")


def upgrade() -> None:
    op.add_column("subjects", sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("subjects", sa.Column("origin", sa.String(length=16), server_default="user", nullable=False))
    op.create_check_constraint("subject_origin_valid", "subjects", "origin IN ('user', 'automatic')")
    op.add_column("subject_concepts", sa.Column("origin", sa.String(length=16), server_default="user", nullable=False))
    op.add_column("subject_concepts", sa.Column("capture_id", sa.UUID(), nullable=True))
    op.add_column("subject_concepts", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("subject_concepts_capture_id_fkey", "subject_concepts", "captures", ["capture_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("subject_membership_origin_valid", "subject_concepts", "origin IN ('user', 'automatic')")

    op.add_column("conversations", sa.Column("subject_id", sa.UUID(), nullable=True))
    op.add_column("conversations", sa.Column("active_activity", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key("fk_conversation_subject", "conversations", "subjects", ["subject_id"], ["id"], ondelete="SET NULL")

    op.add_column("review_sessions", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column("review_sessions", sa.Column("target_count", sa.Integer(), nullable=True))
    op.create_foreign_key("review_sessions_conversation_id_fkey", "review_sessions", "conversations", ["conversation_id"], ["id"], ondelete="SET NULL")
    op.add_column("review_questions", sa.Column("format", sa.String(length=16), server_default="open", nullable=False))
    op.add_column("review_questions", sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("review_questions", sa.Column("answer_key", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table("conversation_turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("capture_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("intents", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("effects", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["capture_id"], ["captures.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capture_id"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_turn_sequence"))
    op.create_index(op.f("ix_conversation_turns_conversation_id"), "conversation_turns", ["conversation_id"], unique=False)

    op.create_table("learning_needs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("concept_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("user_excerpt", sa.Text(), nullable=True),
        sa.Column("revision_id", sa.UUID(), nullable=True),
        sa.Column("evidence", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('gap', 'misconception')", name="learning_need_kind_valid"),
        sa.CheckConstraint("evidence IN ('user_uncertain', 'model_suspected', 'observed_in_answer')", name="learning_need_evidence_valid"),
        sa.CheckConstraint("status IN ('open', 'exploring', 'improved', 'dismissed')", name="learning_need_status_valid"),
        sa.ForeignKeyConstraint(["artifact_id"], ["learning_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["explanation_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_learning_needs_concept_id"), "learning_needs", ["concept_id"], unique=False)
    op.create_table("learning_need_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("need_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('suspected', 'asked', 'answered', 'dismissed')", name="learning_need_event_kind_valid"),
        sa.ForeignKeyConstraint(["need_id"], ["learning_needs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["conversation_turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_learning_need_events_need_id"), "learning_need_events", ["need_id"], unique=False)

    op.drop_constraint("work_kind_valid", "work_items", type_="check")
    op.create_check_constraint("work_kind_valid", "work_items", f"kind IN ({KINDS}, 'turn')")
    op.drop_constraint("work_target_valid", "work_items", type_="check")
    op.create_check_constraint("work_target_valid", "work_items", TARGETS.format("'profile_migration', 'resource_extract', 'learning', 'turn'"))


def downgrade() -> None:
    op.execute("DELETE FROM work_items WHERE kind = 'turn'")
    op.drop_constraint("work_target_valid", "work_items", type_="check")
    op.create_check_constraint("work_target_valid", "work_items", TARGETS.format("'profile_migration', 'resource_extract', 'learning'"))
    op.drop_constraint("work_kind_valid", "work_items", type_="check")
    op.create_check_constraint("work_kind_valid", "work_items", f"kind IN ({KINDS})")
    op.drop_index(op.f("ix_learning_need_events_need_id"), table_name="learning_need_events")
    op.drop_table("learning_need_events")
    op.drop_index(op.f("ix_learning_needs_concept_id"), table_name="learning_needs")
    op.drop_table("learning_needs")
    op.drop_index(op.f("ix_conversation_turns_conversation_id"), table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_column("review_questions", "answer_key")
    op.drop_column("review_questions", "options")
    op.drop_column("review_questions", "format")
    op.drop_constraint("review_sessions_conversation_id_fkey", "review_sessions", type_="foreignkey")
    op.drop_column("review_sessions", "target_count")
    op.drop_column("review_sessions", "conversation_id")
    op.drop_constraint("fk_conversation_subject", "conversations", type_="foreignkey")
    op.drop_column("conversations", "active_activity")
    op.drop_column("conversations", "subject_id")
    op.drop_constraint("subject_membership_origin_valid", "subject_concepts", type_="check")
    op.drop_constraint("subject_concepts_capture_id_fkey", "subject_concepts", type_="foreignkey")
    op.drop_column("subject_concepts", "created_at")
    op.drop_column("subject_concepts", "capture_id")
    op.drop_column("subject_concepts", "origin")
    op.drop_constraint("subject_origin_valid", "subjects", type_="check")
    op.drop_column("subjects", "origin")
    op.drop_column("subjects", "aliases")
