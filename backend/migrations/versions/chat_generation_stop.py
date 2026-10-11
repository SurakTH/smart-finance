"""Durable cancellation gate separate from the long-held worker job lock."""
from alembic import op
import sqlalchemy as sa
revision='chat_generation_stop'
down_revision='assistant_reads'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('chat_generations',sa.Column('job_id',sa.String(36),sa.ForeignKey('jobs.id',ondelete='CASCADE'),primary_key=True),sa.Column('conversation_id',sa.String(36),nullable=False),sa.Column('stop_requested',sa.Boolean(),nullable=False,server_default=sa.false()))
    # Backfill queued work before new API/worker processes start.
    connection=op.get_bind()
    jobs=sa.table('jobs',sa.column('id'),sa.column('task'),sa.column('payload',sa.JSON()),sa.column('status'))
    for row in connection.execute(sa.select(jobs.c.id,jobs.c.payload).where(jobs.c.task=='chat',jobs.c.status=='pending')):
        cid=(row.payload or {}).get('conversation_id')
        if cid:connection.execute(sa.text('INSERT INTO chat_generations (job_id,conversation_id,stop_requested) VALUES (:id,:cid,false)'),dict(id=row.id,cid=cid))
def downgrade():op.drop_table('chat_generations')
