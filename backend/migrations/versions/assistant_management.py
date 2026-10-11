"""Durable append-only audit for human-confirmed assistant management plans."""
from alembic import op
import sqlalchemy as sa
revision='assistant_management'
down_revision='assistant_models'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('assistant_changes',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('action_id',sa.String(36),nullable=False,unique=True),
        sa.Column('summary',sa.String(12000),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('created_at',sa.BigInteger(),nullable=False))
    op.create_index('ix_assistant_changes_workspace_id','assistant_changes',['workspace_id'])
    if op.get_bind().dialect.name=='postgresql':
        op.execute('CREATE TRIGGER sf_assistant_change_immutable BEFORE UPDATE OR DELETE ON assistant_changes FOR EACH ROW EXECUTE FUNCTION sf_immutable()')

def downgrade():op.drop_table('assistant_changes')
