"""Workspace AI configuration and editable model routes; retain existing providers."""
from alembic import op
import sqlalchemy as sa
revision='ai_configuration'
down_revision='email_recovery'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('ai_settings',
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('cloud_enabled',sa.Boolean(),nullable=False),
        sa.Column('demo_fallback',sa.Boolean(),nullable=False),
        sa.Column('max_attempted_providers',sa.Integer(),nullable=False))
    for name,typ,default in [('name',sa.String(100),''),('endpoint',sa.String(500),''),
        ('enabled',sa.Boolean(),sa.true()),('timeout_seconds',sa.Integer(),'20'),
        ('retries',sa.Integer(),'1'),('max_tokens',sa.Integer(),'1200'),('temperature',sa.Integer(),'10')]:
        op.add_column('providers',sa.Column(name,typ,nullable=False,server_default=default))

def downgrade():
    for name in ['temperature','max_tokens','retries','timeout_seconds','enabled','endpoint','name']:
        op.drop_column('providers',name)
    op.drop_table('ai_settings')
