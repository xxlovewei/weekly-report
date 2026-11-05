"""新增版本发版记录表。"""
from alembic import op
from app.models import ReleaseRecord

revision = "0008_release_records"
down_revision = "0007_meeting_assignments"
branch_labels = None
depends_on = None


def upgrade():
    # 初始迁移使用当前模型建表，因此兼容全新安装。
    ReleaseRecord.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("release_records")
