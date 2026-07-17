"""add difficulty, question_count to matches; add composite state+created_at index

Revision ID: 3a9f1c2e8d47
Revises: 11b8e3e66b77
Create Date: 2026-07-17 10:26:00.000000
"""

revision = '3a9f1c2e8d47'
down_revision = '11b8e3e66b77'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('matches', sa.Column('difficulty', sa.String(), nullable=False, server_default='medium'))
    op.add_column('matches', sa.Column('question_count', sa.Integer(), nullable=False, server_default='10'))

    op.create_index('ix_matches_state_created_at', 'matches', ['state', 'created_at'])


def downgrade():
    op.drop_index('ix_matches_state_created_at', table_name='matches')
    op.drop_column('matches', 'question_count')
    op.drop_column('matches', 'difficulty')
