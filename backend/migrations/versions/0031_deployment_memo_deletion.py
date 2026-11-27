"""允许删除个人发版备忘并保留发版历史。"""
import sqlalchemy as sa
from alembic import op

revision = "0031_deployment_memo_deletion"
down_revision = "0030_deployment_plan_refs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deployment_memos", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("deployment_memos", "deleted_at")
