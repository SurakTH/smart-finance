"""Frozen chat drafts; explicit authenticated typed confirmation only."""
from alembic import op
import sqlalchemy as sa
revision='chat_actions'
down_revision='user_profile'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('chat_actions',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('workspace_id',sa.String(36),nullable=False),
        sa.Column('conversation_id',sa.String(36),nullable=False),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('code',sa.String(8),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('expires',sa.BigInteger(),nullable=False),
        sa.Column('created_at',sa.BigInteger(),nullable=False),
        sa.Column('entry_id',sa.String(36),nullable=True),
        sa.ForeignKeyConstraint(['conversation_id','workspace_id'],['conversations.id','conversations.workspace_id']),
        sa.ForeignKeyConstraint(['entry_id','workspace_id'],['entries.id','entries.workspace_id']),
        sa.UniqueConstraint('conversation_id','code'),
        sa.CheckConstraint("status IN ('pending','confirmed','cancelled','superseded','expired','conflict')"))
    op.create_index('ix_chat_actions_workspace_id','chat_actions',['workspace_id'])

def downgrade():
    op.drop_table('chat_actions')
