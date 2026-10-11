"""Track data changes while AI performs network inference without workspace locks."""
from alembic import op
import sqlalchemy as sa
revision='ai_evidence_epoch'
down_revision='ai_diagnostics'
branch_labels=None
depends_on=None
TABLES=('accounts','entries','lines','budgets','entry_revisions','goals','goal_movements','recurring_rules','assistant_preferences','providers','ai_settings','memberships','chat_actions','chat_preferences')

def upgrade():
    op.add_column('workspaces',sa.Column('ai_epoch',sa.BigInteger(),nullable=False,server_default='0'))
    if op.get_bind().dialect.name=='postgresql':
        op.execute("""CREATE FUNCTION sf_ai_epoch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          UPDATE workspaces SET ai_epoch=ai_epoch+1 WHERE id=CASE WHEN TG_OP='DELETE' THEN OLD.workspace_id ELSE NEW.workspace_id END;
          RETURN NULL; END $$""")
        for table in TABLES:op.execute(f'CREATE TRIGGER sf_ai_epoch AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION sf_ai_epoch()')
    else:
        for table in TABLES:
            for action in ('INSERT','UPDATE','DELETE'):
                row='OLD' if action=='DELETE' else 'NEW'
                op.execute(f'CREATE TRIGGER sf_ai_epoch_{table}_{action} AFTER {action} ON {table} BEGIN UPDATE workspaces SET ai_epoch=ai_epoch+1 WHERE id={row}.workspace_id; END')

def downgrade():
    if op.get_bind().dialect.name=='postgresql':
        for table in TABLES:op.execute(f'DROP TRIGGER sf_ai_epoch ON {table}')
        op.execute('DROP FUNCTION sf_ai_epoch()')
    else:
        for table in TABLES:
            for action in ('INSERT','UPDATE','DELETE'):op.execute(f'DROP TRIGGER sf_ai_epoch_{table}_{action}')
    op.drop_column('workspaces','ai_epoch')
