"""Recurring schedules create tenant-scoped proposals requiring manual confirmation."""
from alembic import op
import sqlalchemy as sa
revision='recurring_rules'
down_revision='savings_goals'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('proposals') as batch:batch.create_unique_constraint('uq_proposal_id_workspace',['id','workspace_id'])
    op.create_table('recurring_rules',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('description',sa.String(300),nullable=False),sa.Column('kind',sa.String(20),nullable=False),sa.Column('amount',sa.BigInteger(),nullable=False),
        sa.Column('account_id',sa.String(36),nullable=False),sa.Column('category_id',sa.String(36),nullable=False),sa.Column('frequency',sa.String(10),nullable=False),
        sa.Column('start_on',sa.String(10),nullable=False),sa.Column('next_on',sa.String(10),nullable=False),sa.Column('end_on',sa.String(10),nullable=True),
        sa.Column('paused',sa.Integer(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.Column('checked_at',sa.BigInteger(),nullable=False),
        sa.Column('created_at',sa.BigInteger(),nullable=False),sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('idempotency_key',sa.String(36),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.UniqueConstraint('id','workspace_id'),sa.UniqueConstraint('workspace_id','idempotency_key'),
        sa.ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']),sa.ForeignKeyConstraint(['category_id','workspace_id'],['accounts.id','accounts.workspace_id']),
        sa.CheckConstraint("kind IN ('income','expense')"),sa.CheckConstraint("frequency IN ('daily','weekly','monthly')"),
        sa.CheckConstraint('amount > 0 AND amount <= 100000000000'),sa.CheckConstraint('paused IN (0,1)'),sa.CheckConstraint('version > 0'))
    op.create_index('ix_recurring_rules_workspace_id','recurring_rules',['workspace_id'])
    op.create_index('ix_recurring_rules_due','recurring_rules',['paused','next_on','checked_at'])
    op.create_table('recurring_occurrences',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('rule_id',sa.String(36),nullable=False),sa.Column('proposal_id',sa.String(36),nullable=False,unique=True),
        sa.Column('scheduled_on',sa.String(10),nullable=False),sa.Column('account_id',sa.String(36),nullable=False),sa.Column('category_id',sa.String(36),nullable=False),
        sa.UniqueConstraint('rule_id','scheduled_on'),
        sa.ForeignKeyConstraint(['rule_id','workspace_id'],['recurring_rules.id','recurring_rules.workspace_id']),
        sa.ForeignKeyConstraint(['proposal_id','workspace_id'],['proposals.id','proposals.workspace_id']),
        sa.ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']),sa.ForeignKeyConstraint(['category_id','workspace_id'],['accounts.id','accounts.workspace_id']))
    op.create_index('ix_recurring_occurrences_workspace_id','recurring_occurrences',['workspace_id'])
    if op.get_bind().dialect.name=='postgresql':
        op.execute('CREATE TRIGGER sf_recurring_occurrence_immutable BEFORE UPDATE OR DELETE ON recurring_occurrences FOR EACH ROW EXECUTE FUNCTION sf_immutable()')

def downgrade():
    op.drop_table('recurring_occurrences');op.drop_table('recurring_rules')
    with op.batch_alter_table('proposals') as batch:batch.drop_constraint('uq_proposal_id_workspace',type_='unique')
