"""Personal chat retention and bounded temporary rooms."""
from alembic import op
import sqlalchemy as sa
revision='chat_retention'
down_revision='workspace_members'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('chat_preferences',sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),primary_key=True),sa.Column('retention_days',sa.Integer(),nullable=False),sa.CheckConstraint('retention_days IN (0,7,30,90)'))
    with op.batch_alter_table('conversations',table_args=(sa.CheckConstraint("privacy IN ('private','standard')",name='ck_conversation_privacy'),)) as b:
        b.add_column(sa.Column('temporary',sa.Integer(),nullable=False,server_default='0'))
        b.add_column(sa.Column('created_at',sa.BigInteger(),nullable=False,server_default='0'))
        b.add_column(sa.Column('updated_at',sa.BigInteger(),nullable=False,server_default='0'))
        b.create_check_constraint('ck_conversation_temporary','temporary IN (0,1)')
    # Existing rooms start a fresh retention clock; upgrading never expires old rooms.
    import time
    op.execute(sa.text('UPDATE conversations SET created_at=:n,updated_at=:n').bindparams(n=int(time.time())))
    op.create_index('ix_conversation_retention','conversations',['temporary','updated_at'])

def downgrade():
    op.drop_index('ix_conversation_retention',table_name='conversations')
    with op.batch_alter_table('conversations') as b:
        b.drop_constraint('ck_conversation_temporary',type_='check')
        for name in ('temporary','created_at','updated_at'):b.drop_column(name)
    op.drop_table('chat_preferences')
