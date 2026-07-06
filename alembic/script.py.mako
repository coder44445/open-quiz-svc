
"""${message or ""}
Revision ID: ${up_revision}
Revises: ${down_revision or None}
Create Date: ${create_date}
"""

# alembic revision identifiers
revision = '${up_revision}'
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

def upgrade():
% if upgrades:
${upgrades}
% else:
    pass
% endif

def downgrade():
% if downgrades:
${downgrades}
% else:
    pass
% endif
