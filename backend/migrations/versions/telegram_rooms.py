"""Active Telegram room pointer; old conversation history is retained."""
from alembic import op
import sqlalchemy as sa
revision='telegram_rooms'
down_revision='telegram_assistant'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('telegram_links',sa.Column('conversation_id',sa.String(36),nullable=True))

def downgrade():
    op.drop_column('telegram_links','conversation_id')
