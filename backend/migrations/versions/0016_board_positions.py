"""保存任务看板卡片在列内的位置。"""
from alembic import op
import sqlalchemy as sa

revision = "0016_board_positions"
down_revision = "0015_task_board"
branch_labels = None
depends_on = None


def upgrade():
    columns = sa.inspect(op.get_bind()).get_columns("board_tasks")
    if any(column["name"] == "position" for column in columns):
        return
    op.add_column("board_tasks", sa.Column("position", sa.BigInteger()))
    # 旧看板按 ID 显示，沿用原有顺序。
    op.execute("UPDATE board_tasks SET position = id")
    op.alter_column("board_tasks", "position", nullable=False)


def downgrade():
    op.drop_column("board_tasks", "position")
