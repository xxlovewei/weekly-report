"""保存系统定时任务的开关和执行间隔。"""
from alembic import op
import sqlalchemy as sa

revision = "0014_scheduled_tasks"
down_revision = "0013_user_roles"
branch_labels = None
depends_on = None


def upgrade():
    # 初始迁移使用当前模型建表，全新安装时可能已创建此表。
    if not sa.inspect(op.get_bind()).has_table("scheduled_tasks"):
        op.create_table(
            "scheduled_tasks",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("interval_minutes", sa.Integer(), nullable=False),
            sa.CheckConstraint("interval_minutes BETWEEN 1 AND 1440", name="ck_scheduled_tasks_interval"),
        )


def downgrade():
    op.drop_table("scheduled_tasks")
