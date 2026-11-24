"""记录看板任务完成周。"""
import sqlalchemy as sa
from alembic import op

revision = "0021_board_completion_week"
down_revision = "0020_task_plan_board_sync"
branch_labels = None
depends_on = None


def upgrade():
    # 初始迁移使用当前模型，新安装的数据库可能已有此列。
    if "completed_week" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("board_tasks")}:
        op.add_column("board_tasks", sa.Column("completed_week", sa.Date()))
    # 存量已完成卡片以最新的已完成周明细回填，缺少明细时保留未知。
    op.execute("""
        UPDATE board_tasks AS card SET completed_week = history.completed_week
        FROM (
            SELECT detail.board_task_id, MAX(week.start_date) AS completed_week
            FROM board_task_details AS detail
            JOIN tasks AS task ON task.id = detail.task_id
            JOIN weeks AS week ON week.id = detail.week_id
            WHERE task.status = '已完成'
            GROUP BY detail.board_task_id
        ) AS history
        WHERE card.state = 'done' AND card.id = history.board_task_id
    """)


def downgrade():
    op.drop_column("board_tasks", "completed_week")
