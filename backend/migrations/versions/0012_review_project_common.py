"""为审查项目增加常用状态。"""
from alembic import op
import sqlalchemy as sa

revision = "0012_review_project_common"
down_revision = "0011_notification_events"
branch_labels = None
depends_on = None


def upgrade():
    # 全新安装时，前序迁移使用当前模型建表，可能已包含该列。
    op.add_column(
        "review_projects",
        sa.Column("is_common", sa.Boolean(), nullable=False, server_default=sa.false()),
        if_not_exists=True,
    )


def downgrade():
    op.drop_column("review_projects", "is_common")
