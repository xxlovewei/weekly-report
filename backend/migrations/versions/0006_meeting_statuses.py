"""统一会议任务和周任务的完成状态。"""
from alembic import op

revision = "0006_meeting_statuses"
down_revision = "0005_soft_delete_users"
branch_labels = None
depends_on = None


def upgrade():
    # 旧版未完成没有具体进度，迁移为未开始，保留已完成状态。
    op.execute("UPDATE meeting_tasks SET status = NULL WHERE status = '未完成'")


def downgrade():
    # 旧版仅支持已完成、未完成和空值，百分比进度归为未完成。
    op.execute("UPDATE meeting_tasks SET status = '未完成' WHERE status IS NOT NULL AND status <> '已完成'")
