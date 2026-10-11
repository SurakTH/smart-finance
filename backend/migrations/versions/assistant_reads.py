"""Composite indexes for bounded assistant lookups, history and journals."""
from alembic import op
revision='assistant_reads'
down_revision='assistant_personalization'
branch_labels=None
depends_on=None
INDEXES=[
    ('ix_entries_workspace_cursor','entries',['workspace_id','occurred_on','created_at','id']),
    ('ix_lines_workspace_entry_account','lines',['workspace_id','entry_id','account_id']),
    ('ix_lines_workspace_account_entry','lines',['workspace_id','account_id','entry_id']),
    ('ix_messages_workspace_conversation_cursor','messages',['workspace_id','conversation_id','created_at','id']),
    ('ix_accounts_workspace_kind_cursor','accounts',['workspace_id','kind','id']),
    ('ix_goals_workspace_cursor','goals',['workspace_id','id']),
    ('ix_recurring_workspace_cursor','recurring_rules',['workspace_id','id']),
]
def upgrade():
    for name,table,columns in INDEXES:op.create_index(name,table,columns)
def downgrade():
    for name,table,columns in reversed(INDEXES):op.drop_index(name,table_name=table)
