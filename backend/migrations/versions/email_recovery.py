"""Email ownership and one-use recovery links with encrypted mail outbox."""
from alembic import op
import sqlalchemy as sa
revision='email_recovery'
down_revision='natural_chat'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('email_verified_at',sa.BigInteger(),nullable=True))
    op.create_table('email_tokens',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('purpose',sa.String(12),nullable=False),
        sa.Column('expires',sa.BigInteger(),nullable=False),
        sa.Column('used',sa.Boolean(),nullable=False),
        sa.Column('delivery',sa.String(12),nullable=False),
        sa.Column('encrypted_payload',sa.Text(),nullable=True),
        sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt',sa.BigInteger(),nullable=False),
        sa.CheckConstraint("purpose IN ('reset','verify')"),
        sa.CheckConstraint("delivery IN ('pending','sent','failed','cancelled')"))
    op.create_index('ix_email_tokens_user_id','email_tokens',['user_id'])

def downgrade():
    op.drop_table('email_tokens')
    op.drop_column('users','email_verified_at')
