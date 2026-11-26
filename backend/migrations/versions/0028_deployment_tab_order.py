"""保存各账号的发版管理页签顺序。"""
import sqlalchemy as sa
from alembic import op

revision = "0028_deployment_tab_order"
down_revision = "0027_deployment_upgrade_content"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("deployment_tab_order", sa.JSON(), nullable=False, server_default="[]"),
                  if_not_exists=True)


def downgrade():
    op.drop_column("users", "deployment_tab_order")
