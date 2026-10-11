"""Tenant-scoped images in conversation history."""
from alembic import op
import sqlalchemy as sa
revision='chat_images'
down_revision='proposal_receipt'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('messages') as batch:
        batch.add_column(sa.Column('attachment_id',sa.String(36),nullable=True))
        batch.create_foreign_key('fk_message_attachment_workspace','attachments',['attachment_id','workspace_id'],['id','workspace_id'])

def downgrade():
    with op.batch_alter_table('messages') as batch:
        batch.drop_constraint('fk_message_attachment_workspace',type_='foreignkey')
        batch.drop_column('attachment_id')
