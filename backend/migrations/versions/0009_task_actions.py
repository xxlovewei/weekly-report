"""新增任务优先级和转交来源。"""
from alembic import op
import sqlalchemy as sa

revision = "0009_task_actions"
down_revision = "0008_release_records"
branch_labels = None
depends_on = None


def upgrade():
    # 初始迁移使用当前模型建表，已有数据库按需补列。
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tasks")}
    if "priority" not in columns:
        op.add_column("tasks", sa.Column("priority", sa.String(4), nullable=True))
    if "transferred_by" not in columns:
        op.add_column("tasks", sa.Column("transferred_by", sa.String(120), nullable=True))


def downgrade():
    op.drop_column("tasks", "transferred_by")
    op.drop_column("tasks", "priority")
