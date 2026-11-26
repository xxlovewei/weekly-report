"""保存发版版本选择的 GitLab 标签。"""
import sqlalchemy as sa
from alembic import op

revision = "0026_deployment_tags"
down_revision = "0025_project_deployments"
branch_labels = None
depends_on = None

TAG_COLUMNS = (
    ("tag", sa.String(1000)),
    ("tag_url", sa.Text()),
    ("tag_sha", sa.String(64)),
)


def upgrade():
    # 首次安装时，旧迁移可能已按现行模型建表。
    for name, kind in TAG_COLUMNS:
        op.add_column("deployment_versions", sa.Column(name, kind), if_not_exists=True)


def downgrade():
    for name, _ in reversed(TAG_COLUMNS):
        op.drop_column("deployment_versions", name)
