"""Database-enforced balanced, immutable journals on PostgreSQL."""
from alembic import op

revision='ledger_guards'
down_revision='cf3ab83b26d0'
branch_labels=None
depends_on=None

def upgrade():
    if op.get_bind().dialect.name!='postgresql': return
    op.execute('''
    CREATE FUNCTION sf_check_balance() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE target varchar(36); ws varchar(36); total numeric; n integer;
    BEGIN
      IF TG_TABLE_NAME='entries' THEN target=NEW.id; ws=NEW.workspace_id;
      ELSE target=NEW.entry_id; ws=NEW.workspace_id; END IF;
      SELECT COALESCE(SUM(signed_amount),0),COUNT(*) INTO total,n
      FROM lines WHERE entry_id=target AND workspace_id=ws;
      IF total<>0 OR n<2 THEN RAISE EXCEPTION 'Journal must balance with at least two lines'; END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER sf_balanced_entry AFTER INSERT ON entries
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sf_check_balance();
    CREATE CONSTRAINT TRIGGER sf_balanced_line AFTER INSERT ON lines
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sf_check_balance();
    CREATE FUNCTION sf_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Posted ledger is immutable'; END $$;
    CREATE TRIGGER sf_entry_immutable BEFORE UPDATE OR DELETE ON entries
    FOR EACH ROW EXECUTE FUNCTION sf_immutable();
    CREATE TRIGGER sf_line_immutable BEFORE UPDATE OR DELETE ON lines
    FOR EACH ROW EXECUTE FUNCTION sf_immutable();
    CREATE FUNCTION sf_line_same_transaction() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE entry_xid text;
    BEGIN
      SELECT xmin::text INTO entry_xid FROM entries WHERE id=NEW.entry_id AND workspace_id=NEW.workspace_id;
      IF entry_xid IS DISTINCT FROM pg_current_xact_id()::text THEN
        RAISE EXCEPTION 'Cannot append to a previously posted journal';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER sf_line_fresh BEFORE INSERT ON lines
    FOR EACH ROW EXECUTE FUNCTION sf_line_same_transaction();
    ''')

def downgrade():
    if op.get_bind().dialect.name!='postgresql': return
    op.execute('''
    DROP TRIGGER sf_line_fresh ON lines;
    DROP TRIGGER sf_line_immutable ON lines;
    DROP TRIGGER sf_entry_immutable ON entries;
    DROP TRIGGER sf_balanced_line ON lines;
    DROP TRIGGER sf_balanced_entry ON entries;
    DROP FUNCTION sf_line_same_transaction();
    DROP FUNCTION sf_immutable();
    DROP FUNCTION sf_check_balance();
    ''')
