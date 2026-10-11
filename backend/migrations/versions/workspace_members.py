"""Email-bound invitations and immutable membership audit."""
from alembic import op
import sqlalchemy as sa
revision='workspace_members'
down_revision='recurring_rules'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('invitations',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('email',sa.String(254),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('status',sa.String(12),nullable=False),sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('accepted_by',sa.String(36),sa.ForeignKey('users.id')),sa.Column('created_at',sa.BigInteger(),nullable=False),sa.Column('expires',sa.BigInteger(),nullable=False),
        sa.UniqueConstraint('id','workspace_id'),sa.CheckConstraint("status IN ('pending','accepted','revoked')"))
    op.create_index('ix_invitations_workspace_id','invitations',['workspace_id'])
    op.create_table('membership_events',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),sa.Column('target_id',sa.String(36),sa.ForeignKey('users.id')),
        sa.Column('email',sa.String(254),nullable=False),sa.Column('action',sa.String(25),nullable=False),
        sa.Column('previous_role',sa.String(10)),sa.Column('next_role',sa.String(10)),sa.Column('created_at',sa.BigInteger(),nullable=False),
        sa.CheckConstraint("action IN ('invited','invite_revoked','joined','role_changed','removed','left')"))
    op.create_index('ix_membership_events_workspace_id','membership_events',['workspace_id'])
    if op.get_bind().dialect.name=='postgresql':
        op.execute('CREATE TRIGGER sf_membership_event_immutable BEFORE UPDATE OR DELETE ON membership_events FOR EACH ROW EXECUTE FUNCTION sf_immutable()')
        op.execute("""CREATE FUNCTION sf_keep_workspace_owner() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE w varchar;
        BEGIN
          FOR w IN SELECT id FROM workspaces WHERE id=OLD.workspace_id OR (TG_OP='UPDATE' AND id=NEW.workspace_id) ORDER BY id FOR UPDATE LOOP
            IF NOT EXISTS (SELECT 1 FROM memberships WHERE workspace_id=w AND role='owner') THEN
              RAISE EXCEPTION 'workspace must retain an owner';
            END IF;
          END LOOP;
          RETURN NULL;
        END $$""")
        op.execute('CREATE CONSTRAINT TRIGGER sf_workspace_owner AFTER UPDATE OR DELETE ON memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sf_keep_workspace_owner()')

def downgrade():
    if op.get_bind().dialect.name=='postgresql':
        op.execute('DROP TRIGGER sf_workspace_owner ON memberships');op.execute('DROP FUNCTION sf_keep_workspace_owner()')
    op.drop_table('membership_events');op.drop_table('invitations')
