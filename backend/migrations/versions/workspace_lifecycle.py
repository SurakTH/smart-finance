"""Recoverable workspace archive and private account onboarding invites."""
from alembic import op
import sqlalchemy as sa
revision='workspace_lifecycle'
down_revision='chat_actions'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('workspaces',sa.Column('archived_at',sa.BigInteger(),nullable=True))
    op.add_column('workspaces',sa.Column('version',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('invitations',sa.Column('mode',sa.String(10),nullable=False,server_default='shared'))

def downgrade():
    op.drop_column('invitations','mode');op.drop_column('workspaces','version');op.drop_column('workspaces','archived_at')
