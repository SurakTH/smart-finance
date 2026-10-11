"""Personal display name; existing login identities remain unchanged."""
from alembic import op
import sqlalchemy as sa
revision='user_profile'
down_revision='chat_retention'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('name',sa.String(100),nullable=False,server_default=''))

def downgrade():
    op.drop_column('users','name')
