"""新增项目审查、日报、问题和站内消息表。"""
from alembic import op

from app.models import Notification, ReviewIssue, ReviewProject, ReviewRun

revision = "0010_code_review"
down_revision = "0009_task_actions"
branch_labels = None
depends_on = None

TABLES = (ReviewProject, ReviewRun, ReviewIssue, Notification)


def upgrade():
    for model in TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in reversed(TABLES):
        model.__table__.drop(op.get_bind(), checkfirst=True)
