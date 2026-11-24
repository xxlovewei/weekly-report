"""记录看板引导的展示状态。"""
import sqlalchemy as sa
from alembic import op

revision = "0021_board_task_reminders"
down_revision = "0020_task_plan_board_sync"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("board_reminded", sa.Boolean(), nullable=False,
                                             server_default=sa.false()), if_not_exists=True)
    # 旧版从通知跳转时已显示过提醒，避免在升级后重新提示历史已读消息。
    op.execute("""
        UPDATE notifications SET board_reminded = true
        WHERE is_read AND kind IN ('转交任务', '会议指派')
    """)


def downgrade():
    op.drop_column("notifications", "board_reminded")
