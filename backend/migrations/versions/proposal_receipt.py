"""Link receipt evidence to a proposal within the same workspace."""
from alembic import op
import sqlalchemy as sa
revision='proposal_receipt'
down_revision='ledger_guards'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('proposals') as batch:
        batch.add_column(sa.Column('attachment_id',sa.String(36),nullable=True))
        batch.create_foreign_key('fk_proposal_attachment_workspace','attachments',['attachment_id','workspace_id'],['id','workspace_id'])

def downgrade():
    with op.batch_alter_table('proposals') as batch:
        batch.drop_constraint('fk_proposal_attachment_workspace',type_='foreignkey')
        batch.drop_column('attachment_id')
