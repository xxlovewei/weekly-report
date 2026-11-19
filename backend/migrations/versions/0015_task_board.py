"""新增任务看板及跨周关联，标注任务明细表。"""
import sqlalchemy as sa
from alembic import op

revision = "0015_task_board"
down_revision = "0014_scheduled_tasks"
branch_labels = None
depends_on = None


def upgrade():
    # 初始迁移使用当前元数据，全新数据库可能已经有这两张表。
    schema = sa.inspect(op.get_bind())
    if not schema.has_table("board_tasks"):
        op.create_table(
            "board_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("category_name", sa.String(100), nullable=False),
            sa.Column("priority", sa.String(4), nullable=False),
            sa.Column("state", sa.String(16), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.CheckConstraint("state IN ('inbox', 'in_progress', 'done')", name="ck_board_task_state"),
            sa.CheckConstraint("priority IN ('高', '中', '低')", name="ck_board_task_priority"),
        )
        op.create_index("ix_board_tasks_user_id", "board_tasks", ["user_id"])
    if not schema.has_table("board_task_details"):
        op.create_table(
            "board_task_details",
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("board_task_id", sa.Integer(), sa.ForeignKey("board_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("week_id", sa.Integer(), sa.ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("board_task_id", "week_id"),
        )
    op.execute(sa.text("COMMENT ON TABLE tasks IS '任务明细表'"))


def downgrade():
    op.drop_table("board_task_details")
    op.drop_table("board_tasks")
    op.execute(sa.text("COMMENT ON TABLE tasks IS NULL"))
