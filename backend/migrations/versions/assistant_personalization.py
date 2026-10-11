"""Structured personal preferences and bounded AI usage accounting."""
from alembic import op
import sqlalchemy as sa
revision='assistant_personalization'
down_revision='assistant_management'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('messages',sa.Column('references',sa.JSON(),nullable=True))
    op.create_table('assistant_preferences',sa.Column('user_id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),primary_key=True),sa.Column('values',sa.JSON(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.ForeignKeyConstraint(['user_id','workspace_id'],['memberships.user_id','memberships.workspace_id'],ondelete='CASCADE'))
    op.create_table('ai_usage_policies',sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),primary_key=True),sa.Column('monthly_limit',sa.BigInteger(),nullable=False),sa.Column('prices',sa.JSON(),nullable=False))
    op.create_table('ai_usage',sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),sa.Column('provider_id',sa.String(36),nullable=False),sa.Column('model',sa.String(100),nullable=False),sa.Column('task',sa.String(15),nullable=False),sa.Column('month',sa.String(7),nullable=False),sa.Column('input_tokens',sa.BigInteger(),nullable=False),sa.Column('output_tokens',sa.BigInteger(),nullable=False),sa.Column('cost',sa.BigInteger(),nullable=True),sa.Column('estimated',sa.Boolean(),nullable=False),sa.Column('status',sa.String(15),nullable=False),sa.Column('created_at',sa.BigInteger(),nullable=False))
    op.create_index('ix_ai_usage_workspace_id','ai_usage',['workspace_id'])
    op.create_index('ix_ai_usage_month','ai_usage',['workspace_id','month'])
def downgrade():
    op.drop_column('messages','references')
    op.drop_table('ai_usage');op.drop_table('ai_usage_policies');op.drop_table('assistant_preferences')
