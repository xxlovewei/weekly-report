"""记录发版失败后的实际回滚时间。"""
import sqlalchemy as sa
from alembic import op

revision = "0029_deployment_release_result"
down_revision = "0028_deployment_tab_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deployment_plans", sa.Column("rolled_back_at", sa.DateTime(timezone=True)), if_not_exists=True)


def downgrade():
    op.drop_column("deployment_plans", "rolled_back_at")
