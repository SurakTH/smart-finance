"""Immutable correction audit, scoped references and exact inverse journals."""
from alembic import op
import sqlalchemy as sa
revision='entry_revisions'
down_revision='monthly_budgets'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('entry_revisions',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('original_id',sa.String(36),nullable=False,unique=True),
        sa.Column('reversal_id',sa.String(36),nullable=False,unique=True),
        sa.Column('replacement_id',sa.String(36),nullable=True,unique=True),
        sa.Column('reason',sa.String(300),nullable=False),
        sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.BigInteger(),nullable=False),
        sa.Column('idempotency_key',sa.String(36),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.UniqueConstraint('workspace_id','idempotency_key'),
        *[sa.ForeignKeyConstraint([col,'workspace_id'],['entries.id','entries.workspace_id']) for col in ('original_id','reversal_id','replacement_id')],
        sa.CheckConstraint('original_id != reversal_id AND (replacement_id IS NULL OR (replacement_id != original_id AND replacement_id != reversal_id))'))
    op.create_index('ix_entry_revisions_workspace_id','entry_revisions',['workspace_id'])
    if op.get_bind().dialect.name!='postgresql': return
    op.execute('''
    CREATE TRIGGER sf_revision_immutable BEFORE UPDATE OR DELETE ON entry_revisions
    FOR EACH ROW EXECUTE FUNCTION sf_immutable();
    CREATE FUNCTION sf_revision_check() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM entries WHERE workspace_id=NEW.workspace_id
          AND id IN (NEW.reversal_id,NEW.replacement_id) AND xmin::text<>pg_current_xact_id()::text) THEN
        RAISE EXCEPTION 'Correction journals must be fresh';
      END IF;
      IF EXISTS (SELECT 1 FROM entry_revisions WHERE workspace_id=NEW.workspace_id
          AND (original_id=NEW.original_id OR reversal_id=NEW.original_id
               OR reversal_id=NEW.reversal_id OR replacement_id=NEW.reversal_id)) THEN
        RAISE EXCEPTION 'Correction role already used';
      END IF;
      IF EXISTS (
        SELECT account_id FROM lines WHERE workspace_id=NEW.workspace_id AND entry_id IN (NEW.original_id,NEW.reversal_id)
        GROUP BY account_id HAVING sum(signed_amount)<>0
      ) OR (SELECT count(*) FROM lines WHERE workspace_id=NEW.workspace_id AND entry_id=NEW.original_id)<2
        OR (SELECT count(*) FROM lines WHERE workspace_id=NEW.workspace_id AND entry_id=NEW.reversal_id)<2 THEN
        RAISE EXCEPTION 'Reversal must exactly offset original accounts';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER sf_revision_valid BEFORE INSERT ON entry_revisions
    FOR EACH ROW EXECUTE FUNCTION sf_revision_check();
    ''')

def downgrade():
    op.drop_table('entry_revisions')
    if op.get_bind().dialect.name=='postgresql': op.execute('DROP FUNCTION sf_revision_check()')
