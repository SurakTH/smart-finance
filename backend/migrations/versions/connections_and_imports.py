"""Shared AI credentials and reviewable, idempotent statement imports."""
import uuid
from alembic import op
import sqlalchemy as sa
revision='connections_and_imports'
down_revision='telegram_all_replies'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('ai_connections',sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),sa.Column('name',sa.String(100),nullable=False),sa.Column('kind',sa.String(20),nullable=False),sa.Column('endpoint',sa.String(500),nullable=False),sa.Column('encrypted_key',sa.Text(),nullable=False),sa.UniqueConstraint('id','workspace_id'))
    op.create_index('ix_ai_connections_workspace_id','ai_connections',['workspace_id'])
    with op.batch_alter_table('providers') as batch:
        batch.add_column(sa.Column('connection_id',sa.String(36),nullable=True))
        batch.create_foreign_key('fk_provider_connection_workspace','ai_connections',['connection_id','workspace_id'],['id','workspace_id'])
    conn=op.get_bind()
    # Preserve every endpoint/key separately; never merge credentials by URL alone.
    providers=conn.execute(sa.text('SELECT id,workspace_id,name,model,kind,endpoint,encrypted_key FROM providers')).mappings().all()
    for p in providers:
        cid=str(uuid.uuid4())
        conn.execute(sa.text('INSERT INTO ai_connections (id,workspace_id,name,kind,endpoint,encrypted_key) VALUES (:id,:wid,:name,:kind,:endpoint,:key)'),dict(id=cid,wid=p['workspace_id'],name=p['name'] or p['model'],kind=p['kind'],endpoint=p['endpoint'],key=p['encrypted_key']))
        conn.execute(sa.text("UPDATE providers SET connection_id=:cid, encrypted_key='' WHERE id=:pid"),dict(cid=cid,pid=p['id']))
    op.create_table('statement_imports',sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('account_id',sa.String(36),nullable=False),sa.Column('rows',sa.JSON(),nullable=False),sa.Column('created_at',sa.BigInteger(),nullable=False),sa.Column('confirmed_digest',sa.String(64),nullable=True),sa.Column('result',sa.JSON(),nullable=True),sa.ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']))
    op.create_index('ix_statement_imports_workspace_id','statement_imports',['workspace_id'])
    op.create_table('statement_rows',sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),sa.Column('account_id',sa.String(36),nullable=False),sa.Column('digest',sa.String(64),nullable=False),sa.Column('entry_id',sa.String(36),nullable=False),sa.UniqueConstraint('workspace_id','account_id','digest'),sa.ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']),sa.ForeignKeyConstraint(['entry_id','workspace_id'],['entries.id','entries.workspace_id']))
    op.create_index('ix_statement_rows_workspace_id','statement_rows',['workspace_id'])


def downgrade():
    op.drop_table('statement_rows');op.drop_table('statement_imports')
    op.execute("UPDATE providers SET encrypted_key=COALESCE((SELECT encrypted_key FROM ai_connections WHERE ai_connections.id=providers.connection_id AND ai_connections.workspace_id=providers.workspace_id),'') WHERE connection_id IS NOT NULL")
    with op.batch_alter_table('providers') as batch:
        batch.drop_constraint('fk_provider_connection_workspace',type_='foreignkey')
        batch.drop_column('connection_id')
    op.drop_table('ai_connections')
