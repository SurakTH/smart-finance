"""Trusted text capture follow-up context."""
from alembic import op
import sqlalchemy as sa
revision='natural_chat'
down_revision='workspace_lifecycle'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('conversations',sa.Column('capture_context',sa.JSON(),nullable=True))

def downgrade():
    op.drop_column('conversations','capture_context')
