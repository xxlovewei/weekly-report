"""关联任务计划与看板，并保存看板备注。"""
import sqlalchemy as sa
from alembic import op

revision = "0020_task_plan_board_sync"
down_revision = "0019_review_issue_board"
branch_labels = None
depends_on = None


def upgrade():
    schema = sa.inspect(op.get_bind())
    if "board_task_id" not in {column["name"] for column in schema.get_columns("task_plans")}:
        op.add_column("task_plans", sa.Column("board_task_id", sa.Integer()))
        op.create_foreign_key("task_plans_board_task_id_fkey", "task_plans", "board_tasks",
                              ["board_task_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_task_plans_board_task_id", "task_plans", ["board_task_id"])
    if "notes" not in {column["name"] for column in schema.get_columns("board_tasks")}:
        op.add_column("board_tasks", sa.Column("notes", sa.Text(), nullable=False, server_default=""))
    # 已有关联明细取最近一周的备注，待接收的转交任务取暂存备注。
    op.execute("""
        UPDATE board_tasks b SET notes = COALESCE(
            (SELECT t.notes FROM board_task_details d
             JOIN tasks t ON t.id = d.task_id JOIN weeks w ON w.id = d.week_id
             WHERE d.board_task_id = b.id ORDER BY w.start_date DESC, t.id DESC LIMIT 1),
            b.handoff->>'notes', '')
    """)


def downgrade():
    op.drop_index("ix_task_plans_board_task_id", table_name="task_plans")
    op.drop_column("task_plans", "board_task_id")
    op.drop_column("board_tasks", "notes")
