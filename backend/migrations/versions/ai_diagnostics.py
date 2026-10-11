"""Privacy-preserving AI diagnostics, including isolated test results."""
from alembic import op
import sqlalchemy as sa
revision='ai_diagnostics'
down_revision='chat_generation_stop'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('jobs',sa.Column('diagnostics',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('jobs',sa.Column('diagnostics_expires',sa.BigInteger(),nullable=True))
    op.create_index('ix_jobs_diagnostics_expires','jobs',['diagnostics_expires'])
    op.create_index('ix_jobs_workspace_created','jobs',['workspace_id','created_at','id'])

def downgrade():
    op.drop_index('ix_jobs_workspace_created',table_name='jobs')
    op.drop_index('ix_jobs_diagnostics_expires',table_name='jobs')
    op.drop_column('jobs','diagnostics_expires')
    op.drop_column('jobs','diagnostics')
