"""Preserve normalized receipt evidence on a reviewed Inbox proposal."""
from alembic import op
import sqlalchemy as sa
revision='receipt_readings'
down_revision='connections_and_imports'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('proposals') as batch:
        batch.add_column(sa.Column('receipt',sa.JSON(),nullable=True))

def downgrade():
    with op.batch_alter_table('proposals') as batch:
        batch.drop_column('receipt')
