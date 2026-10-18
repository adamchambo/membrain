"""Distinguish user understanding from formatting and AI suggestions.

Revision ID: 20261018_02
Revises: 4f925718a5c6
"""

from alembic import op
import sqlalchemy as sa


revision = "20261018_02"
down_revision = "4f925718a5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    old_origins = connection.execute(
        sa.text("SELECT count(*) FROM explanation_revisions WHERE origin <> 'user_written'")
    ).scalar_one()
    old_proposals = connection.execute(sa.text("SELECT count(*) FROM ai_proposals")).scalar_one()
    if old_origins or old_proposals:
        raise RuntimeError(
            "Classify existing AI proposal and explanation rows before applying "
            "the user-understanding provenance migration."
        )

    op.add_column("ai_proposals", sa.Column("kind", sa.String(length=32), nullable=False))
    op.create_check_constraint(
        "proposal_kind_valid",
        "ai_proposals",
        "kind IN ('formatting', 'correction', 'gap', 'relationship', 'clarification', 'resource')",
    )

    op.drop_constraint("explanation_origin_valid", "explanation_revisions", type_="check")
    op.create_check_constraint(
        "explanation_origin_valid",
        "explanation_revisions",
        "origin IN ('user_written', 'ai_formatted_user_input', 'user_edited_format')",
    )
    op.create_check_constraint(
        "ai_formatted_provenance_required",
        "explanation_revisions",
        "origin = 'user_written' OR (capture_id IS NOT NULL AND proposal_id IS NOT NULL)",
    )
    op.drop_constraint("explanation_revisions_capture_id_fkey", "explanation_revisions", type_="foreignkey")
    op.drop_constraint("explanation_revisions_proposal_id_fkey", "explanation_revisions", type_="foreignkey")
    op.create_foreign_key(
        "explanation_revisions_capture_id_fkey",
        "explanation_revisions",
        "captures",
        ["capture_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "explanation_revisions_proposal_id_fkey",
        "explanation_revisions",
        "ai_proposals",
        ["proposal_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    new_origins = connection.execute(
        sa.text("SELECT count(*) FROM explanation_revisions WHERE origin <> 'user_written'")
    ).scalar_one()
    if new_origins:
        raise RuntimeError("Remove or export formatted explanation rows before downgrading.")

    op.drop_constraint("explanation_revisions_proposal_id_fkey", "explanation_revisions", type_="foreignkey")
    op.drop_constraint("explanation_revisions_capture_id_fkey", "explanation_revisions", type_="foreignkey")
    op.create_foreign_key(
        "explanation_revisions_capture_id_fkey",
        "explanation_revisions",
        "captures",
        ["capture_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "explanation_revisions_proposal_id_fkey",
        "explanation_revisions",
        "ai_proposals",
        ["proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ai_formatted_provenance_required", "explanation_revisions", type_="check")
    op.drop_constraint("explanation_origin_valid", "explanation_revisions", type_="check")
    op.create_check_constraint(
        "explanation_origin_valid",
        "explanation_revisions",
        "origin IN ('user_written', 'user_edited_ai', 'approved_ai')",
    )
    op.drop_constraint("proposal_kind_valid", "ai_proposals", type_="check")
    op.drop_column("ai_proposals", "kind")
