"""Persist review questions before answers and queue recall feedback.

Revision ID: 20261019_02
Revises: 20261019_01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261019_02"
down_revision = "20261019_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("review_questions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("review_session_id", sa.UUID(), sa.ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.UUID(), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.UUID(), sa.ForeignKey("explanation_revisions.id"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_key", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_review_questions_review_session_id", "review_questions", ["review_session_id"])
    op.add_column("review_attempts", sa.Column("question_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_attempt_question", "review_attempts", "review_questions", ["question_id"], ["id"])
    op.create_unique_constraint("uq_attempt_question", "review_attempts", ["question_id"])
    op.add_column("work_items", sa.Column("attempt_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_work_attempt", "work_items", "review_attempts", ["attempt_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_work_items_attempt_id", "work_items", ["attempt_id"])
    op.drop_constraint("work_kind_valid", "work_items", type_="check")
    op.create_check_constraint("work_kind_valid", "work_items", "kind IN ('capture', 'embedding', 'review_feedback')")
    op.drop_constraint("work_target_valid", "work_items", type_="check")
    op.create_check_constraint("work_target_valid", "work_items",
        "(kind = 'capture' AND capture_id IS NOT NULL AND revision_id IS NULL AND attempt_id IS NULL) OR "
        "(kind = 'embedding' AND revision_id IS NOT NULL AND capture_id IS NULL AND attempt_id IS NULL) OR "
        "(kind = 'review_feedback' AND attempt_id IS NOT NULL AND capture_id IS NULL AND revision_id IS NULL)")


def downgrade():
    # Dropping review feedback work is an explicit downgrade of this feature.
    op.execute("DELETE FROM work_items WHERE kind = 'review_feedback'")
    op.drop_constraint("work_target_valid", "work_items", type_="check")
    op.create_check_constraint("work_target_valid", "work_items",
        "(kind = 'capture' AND capture_id IS NOT NULL AND revision_id IS NULL) OR "
        "(kind = 'embedding' AND revision_id IS NOT NULL AND capture_id IS NULL)")
    op.drop_constraint("work_kind_valid", "work_items", type_="check")
    op.create_check_constraint("work_kind_valid", "work_items", "kind IN ('capture', 'embedding')")
    op.drop_index("ix_work_items_attempt_id", table_name="work_items")
    op.drop_constraint("fk_work_attempt", "work_items", type_="foreignkey")
    op.drop_column("work_items", "attempt_id")
    op.drop_constraint("uq_attempt_question", "review_attempts", type_="unique")
    op.drop_constraint("fk_attempt_question", "review_attempts", type_="foreignkey")
    op.drop_column("review_attempts", "question_id")
    op.drop_table("review_questions")
