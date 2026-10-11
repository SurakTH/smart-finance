"""Workspace savings plans with append-only allocation history."""
from alembic import op
import sqlalchemy as sa
revision='savings_goals'
down_revision='entry_revisions'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('goals',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('name',sa.String(100),nullable=False),sa.Column('target',sa.BigInteger(),nullable=False),
        sa.Column('due_on',sa.String(10),nullable=True),sa.Column('archived',sa.Integer(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.BigInteger(),nullable=False),sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('idempotency_key',sa.String(36),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.UniqueConstraint('id','workspace_id'),sa.UniqueConstraint('workspace_id','idempotency_key'),
        sa.CheckConstraint('target > 0 AND target <= 100000000000'),sa.CheckConstraint('archived IN (0,1)'),sa.CheckConstraint('version > 0'))
    op.create_index('ix_goals_workspace_id','goals',['workspace_id'])
    op.create_table('goal_movements',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('goal_id',sa.String(36),nullable=False),sa.Column('signed_amount',sa.BigInteger(),nullable=False),
        sa.Column('note',sa.String(300),nullable=False),sa.Column('occurred_on',sa.String(10),nullable=False),sa.Column('created_at',sa.BigInteger(),nullable=False),
        sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('idempotency_key',sa.String(36),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.ForeignKeyConstraint(['goal_id','workspace_id'],['goals.id','goals.workspace_id']),sa.UniqueConstraint('workspace_id','idempotency_key'),
        sa.CheckConstraint('signed_amount != 0 AND signed_amount BETWEEN -100000000000 AND 100000000000'))
    op.create_index('ix_goal_movements_workspace_id','goal_movements',['workspace_id'])
    if op.get_bind().dialect.name!='postgresql':return
    op.execute('''
    CREATE TRIGGER sf_goal_movement_immutable BEFORE UPDATE OR DELETE ON goal_movements
    FOR EACH ROW EXECUTE FUNCTION sf_immutable();
    CREATE FUNCTION sf_goal_amount_check() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE total numeric;
    BEGIN
      PERFORM 1 FROM goals WHERE id=NEW.goal_id AND workspace_id=NEW.workspace_id FOR UPDATE;
      SELECT COALESCE(SUM(signed_amount),0) INTO total FROM goal_movements WHERE goal_id=NEW.goal_id AND workspace_id=NEW.workspace_id;
      IF total<0 OR total>100000000000 THEN RAISE EXCEPTION 'Goal allocation outside allowed range'; END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER sf_goal_amount_valid AFTER INSERT ON goal_movements
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sf_goal_amount_check();
    ''')

def downgrade():
    op.drop_table('goal_movements')
    if op.get_bind().dialect.name=='postgresql':op.execute('DROP FUNCTION sf_goal_amount_check()')
    op.drop_table('goals')
