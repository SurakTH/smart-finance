"""Per-model reasoning and vision capabilities. Existing routes retain their defaults."""
from alembic import op
import sqlalchemy as sa
revision='assistant_models'
down_revision='ai_configuration'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('providers',sa.Column('reasoning_effort',sa.String(12),nullable=False,server_default='default'))
    op.add_column('providers',sa.Column('supports_images',sa.Boolean(),nullable=False,server_default=sa.false()))

def downgrade():
    op.drop_column('providers','supports_images')
    op.drop_column('providers','reasoning_effort')
