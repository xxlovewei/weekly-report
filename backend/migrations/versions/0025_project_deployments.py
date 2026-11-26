"""增加审查项目的部署配置及发版管理表。"""
import sqlalchemy as sa
from alembic import op

from app.deploy_models import DeploymentItem, DeploymentMemo, DeploymentMemoTarget, DeploymentPlan, DeploymentVersion

revision = "0025_project_deployments"
down_revision = "0024_board_pending_status"
branch_labels = None
depends_on = None

TABLES = (DeploymentVersion, DeploymentPlan, DeploymentMemo, DeploymentMemoTarget, DeploymentItem)


def upgrade():
    # 首次安装时初始迁移已按当前模型建表。
    for column in ("deployment_level", "deployment_network"):
        op.add_column("review_projects", sa.Column(column, sa.String(16)), if_not_exists=True)
    for model in TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in reversed(TABLES):
        model.__table__.drop(op.get_bind(), checkfirst=True)
    op.drop_column("review_projects", "deployment_network")
    op.drop_column("review_projects", "deployment_level")
