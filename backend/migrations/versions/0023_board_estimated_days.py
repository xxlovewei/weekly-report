"""看板卡片存储以人天为单位的预估工时。"""
import sqlalchemy as sa
from alembic import op

revision = "0023_board_estimated_days"
down_revision = "0022_board_completion_week"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("board_tasks", sa.Column("estimated_days", sa.Numeric()), if_not_exists=True)


def downgrade():
    op.drop_column("board_tasks", "estimated_days")
