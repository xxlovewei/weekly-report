"""保存在加入本周工作前从看板调整的任务进度。"""
import sqlalchemy as sa
from alembic import op

revision = "0024_board_pending_status"
down_revision = "0023_board_estimated_days"
branch_labels = None
depends_on = None


def upgrade():
    # 全新安装时，早期看板迁移使用现行模型建表，可能已包含这个字段。
    op.add_column("board_tasks", sa.Column("pending_status", sa.String(16)), if_not_exists=True)


def downgrade():
    op.drop_column("board_tasks", "pending_status")
