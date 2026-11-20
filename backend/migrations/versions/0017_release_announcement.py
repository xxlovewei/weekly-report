"""单独记录通过上线检查后发出的版本通知。"""
import sqlalchemy as sa
from alembic import op

revision = "0017_release_announcement"
down_revision = "0016_board_positions"
branch_labels = None
depends_on = None


def upgrade():
    # 空库的初始迁移使用当前模型，可能已经创建该字段。
    op.add_column("release_records", sa.Column("announced_at", sa.DateTime(timezone=True)), if_not_exists=True)


def downgrade():
    op.drop_column("release_records", "announced_at")
