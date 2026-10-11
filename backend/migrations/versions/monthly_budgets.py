"""Monthly category budgets, scoped to the owning workspace."""
from alembic import op
import sqlalchemy as sa
revision='monthly_budgets'
down_revision='chat_images'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('budgets',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('category_id',sa.String(36),nullable=False),
        sa.Column('month',sa.String(7),nullable=False),
        sa.Column('amount',sa.BigInteger(),nullable=False),
        sa.ForeignKeyConstraint(['category_id','workspace_id'],['accounts.id','accounts.workspace_id'],name='fk_budget_category_workspace'),
        sa.UniqueConstraint('workspace_id','month','category_id',name='uq_budget_month_category'),
        sa.CheckConstraint('amount > 0 AND amount <= 100000000000',name='ck_budget_amount'))
    op.create_index('ix_budgets_workspace_id','budgets',['workspace_id'])

def downgrade():
    op.drop_index('ix_budgets_workspace_id',table_name='budgets')
    op.drop_table('budgets')
