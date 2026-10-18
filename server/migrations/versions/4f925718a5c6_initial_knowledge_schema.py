"""initial knowledge schema

Revision ID: 4f925718a5c6
Revises: 20261017_01
Create Date: 2026-10-18 17:15:36.871363
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import VECTOR

revision: str = '4f925718a5c6'
down_revision: Union[str, None] = '20261017_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('captures',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('input_kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'processed', 'archived')", name='capture_status_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('concepts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('review_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('requested_scope', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_proposals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('capture_id', sa.UUID(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model_key', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name='proposal_status_valid'),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_proposals_capture_id'), 'ai_proposals', ['capture_id'], unique=False)
    op.create_table('capture_concepts',
    sa.Column('capture_id', sa.UUID(), nullable=False),
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('capture_id', 'concept_id')
    )
    op.create_table('concept_relationships',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source_concept_id', sa.UUID(), nullable=False),
    sa.Column('target_concept_id', sa.UUID(), nullable=False),
    sa.Column('relation_type', sa.String(length=64), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('source_concept_id <> target_concept_id', name='concept_relationship_distinct'),
    sa.ForeignKeyConstraint(['source_concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_concept_id', 'target_concept_id', 'relation_type', name='uq_concept_relationship')
    )
    op.create_table('resources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('capture_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('uri', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('review_attempts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('review_session_id', sa.UUID(), nullable=False),
    sa.Column('format', sa.String(length=32), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('response', sa.Text(), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['review_session_id'], ['review_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_attempts_review_session_id'), 'review_attempts', ['review_session_id'], unique=False)
    op.create_table('review_scope_concepts',
    sa.Column('review_session_id', sa.UUID(), nullable=False),
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_session_id'], ['review_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('review_session_id', 'concept_id')
    )
    op.create_table('concept_resources',
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('concept_id', 'resource_id')
    )
    op.create_table('explanation_revisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.Column('capture_id', sa.UUID(), nullable=True),
    sa.Column('proposal_id', sa.UUID(), nullable=True),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('user_written', 'user_edited_ai', 'approved_ai')", name='explanation_origin_valid'),
    sa.CheckConstraint('revision_number > 0', name='explanation_revision_positive'),
    sa.ForeignKeyConstraint(['capture_id'], ['captures.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['proposal_id'], ['ai_proposals.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('concept_id', 'revision_number', name='uq_explanation_revision_number')
    )
    op.create_index(op.f('ix_explanation_revisions_concept_id'), 'explanation_revisions', ['concept_id'], unique=False)
    op.create_table('review_attempt_concepts',
    sa.Column('review_attempt_id', sa.UUID(), nullable=False),
    sa.Column('concept_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['concept_id'], ['concepts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_attempt_id'], ['review_attempts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('review_attempt_id', 'concept_id')
    )
    op.create_table('concept_embeddings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('explanation_revision_id', sa.UUID(), nullable=False),
    sa.Column('model_key', sa.String(length=255), nullable=False),
    sa.Column('embedding', VECTOR(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['explanation_revision_id'], ['explanation_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('explanation_revision_id', 'model_key', name='uq_concept_embedding_model')
    )


def downgrade() -> None:
    op.drop_table('concept_embeddings')
    op.drop_table('review_attempt_concepts')
    op.drop_index(op.f('ix_explanation_revisions_concept_id'), table_name='explanation_revisions')
    op.drop_table('explanation_revisions')
    op.drop_table('concept_resources')
    op.drop_table('review_scope_concepts')
    op.drop_index(op.f('ix_review_attempts_review_session_id'), table_name='review_attempts')
    op.drop_table('review_attempts')
    op.drop_table('resources')
    op.drop_table('concept_relationships')
    op.drop_table('capture_concepts')
    op.drop_index(op.f('ix_ai_proposals_capture_id'), table_name='ai_proposals')
    op.drop_table('ai_proposals')
    op.drop_table('review_sessions')
    op.drop_table('concepts')
    op.drop_table('captures')
