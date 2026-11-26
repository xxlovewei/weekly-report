"""保存升级计划单独选择的 GitLab 引用。"""
import sqlalchemy as sa
from alembic import op

revision = "0030_deployment_plan_refs"
down_revision = "0029_deployment_release_result"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deployment_plans", sa.Column("version_refs", sa.JSON()), if_not_exists=True)


def downgrade():
    op.drop_column("deployment_plans", "version_refs")
