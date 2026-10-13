"""Durable delivery of synchronous Telegram replies as well as AI job results."""
from alembic import op
import sqlalchemy as sa
revision='telegram_all_replies'
down_revision='telegram_rooms'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('telegram_deliveries',sa.Column('id',sa.String(36),nullable=True))
    op.add_column('telegram_deliveries',sa.Column('body',sa.Text(),nullable=True))
    op.add_column('telegram_deliveries',sa.Column('created_at',sa.BigInteger(),nullable=True))
    op.execute('UPDATE telegram_deliveries SET id=job_id, created_at=(SELECT created_at FROM jobs WHERE jobs.id=telegram_deliveries.job_id)')
    inspector=sa.inspect(op.get_bind())
    pk=inspector.get_pk_constraint('telegram_deliveries')['name'] or 'pk_telegram_deliveries'
    # Alembic cannot reflect an unnamed SQLite CHECK during table recreation.
    checks=(sa.CheckConstraint("status IN ('pending','sent','cancelled','failed')",name='ck_telegram_delivery_status'),) if any(not c['name'] for c in inspector.get_check_constraints('telegram_deliveries')) else ()
    with op.batch_alter_table('telegram_deliveries',recreate='always',naming_convention={'pk':'pk_%(table_name)s'},table_args=checks) as batch:
        batch.drop_constraint(pk,type_='primary')
        batch.create_primary_key('pk_telegram_deliveries',['id'])
        batch.alter_column('created_at',existing_type=sa.BigInteger(),nullable=False)
        batch.alter_column('id',existing_type=sa.String(36),nullable=False)
        batch.alter_column('job_id',existing_type=sa.String(36),nullable=True)
        batch.create_unique_constraint('uq_telegram_delivery_job',['job_id'])


def downgrade():
    # Synchronous deliveries have no representation in the old schema.
    op.execute('DELETE FROM telegram_deliveries WHERE job_id IS NULL')
    with op.batch_alter_table('telegram_deliveries',recreate='always') as batch:
        batch.drop_constraint('pk_telegram_deliveries',type_='primary')
        batch.drop_constraint('uq_telegram_delivery_job',type_='unique')
        batch.create_primary_key('telegram_deliveries_pkey',['job_id'])
        batch.alter_column('job_id',existing_type=sa.String(36),nullable=False)
        batch.drop_column('id')
        batch.drop_column('body')
        batch.drop_column('created_at')
