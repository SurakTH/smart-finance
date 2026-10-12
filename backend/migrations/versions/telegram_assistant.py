"""Durable Telegram assistant result delivery, scoped to a conversation."""
from alembic import op
import sqlalchemy as sa
revision='telegram_assistant'
down_revision='ai_evidence_epoch'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('telegram_deliveries',
        sa.Column('job_id',sa.String(36),sa.ForeignKey('jobs.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('workspace_id',sa.String(36),nullable=False),
        sa.Column('conversation_id',sa.String(36),nullable=False),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('telegram_id',sa.String(30),nullable=False),
        sa.Column('reply_message_id',sa.String(36),nullable=True),
        sa.Column('status',sa.String(15),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('part',sa.Integer(),nullable=False),
        sa.Column('next_attempt',sa.BigInteger(),nullable=False),
        sa.ForeignKeyConstraint(['conversation_id','workspace_id'],['conversations.id','conversations.workspace_id'],ondelete='CASCADE'),
        sa.CheckConstraint("status IN ('pending','sent','cancelled','failed')"))
    op.create_index('ix_telegram_delivery_pending','telegram_deliveries',['status','next_attempt'])


def downgrade():
    op.drop_table('telegram_deliveries')
