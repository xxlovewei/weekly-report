"""允许省略 GitLab 分支，并保存多行升级内容。"""
import sqlalchemy as sa
from alembic import op

revision = "0027_deployment_upgrade_content"
down_revision = "0026_deployment_tags"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("deployment_versions", "branch", nullable=True)
    op.alter_column("deployment_versions", "branch_url", nullable=True)
    # 全新数据库可能已由初始迁移按当前模型建表。
    op.add_column("deployment_plans", sa.Column("upgrade_content", sa.Text(), nullable=False, server_default=""),
                  if_not_exists=True)


def downgrade():
    op.drop_column("deployment_plans", "upgrade_content")
    op.execute("UPDATE deployment_versions SET branch = '', branch_url = '' WHERE branch IS NULL")
    op.alter_column("deployment_versions", "branch_url", nullable=False)
    op.alter_column("deployment_versions", "branch", nullable=False)
