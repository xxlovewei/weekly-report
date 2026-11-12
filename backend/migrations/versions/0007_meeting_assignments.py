"""会议指派与周任务关联。"""
from alembic import op
import sqlalchemy as sa

revision = "0007_meeting_assignments"
down_revision = "0006_meeting_statuses"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    # 初始迁移使用当前模型建表，因此兼容全新安装和已有数据库。
    if "revision" not in {c["name"] for c in inspector.get_columns("meetings")}:
        op.add_column("meetings", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("meeting_tasks", "name", type_=sa.Text(), existing_type=sa.String(500))
    if "meeting_task_id" not in {c["name"] for c in inspector.get_columns("tasks")}:
        op.add_column("tasks", sa.Column("meeting_task_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_tasks_meeting_task", "tasks", "meeting_tasks", ["meeting_task_id"], ["id"], ondelete="RESTRICT")
        op.create_index("ix_tasks_meeting_task_id", "tasks", ["meeting_task_id"])


def downgrade():
    op.drop_index("ix_tasks_meeting_task_id", table_name="tasks")
    op.drop_constraint("fk_tasks_meeting_task", "tasks", type_="foreignkey")
    op.drop_column("tasks", "meeting_task_id")
    # 长描述无法无损还原为旧版 500 字段，保留 Text 类型。
    op.drop_column("meetings", "revision")
