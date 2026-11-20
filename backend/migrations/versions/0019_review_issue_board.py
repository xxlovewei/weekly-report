"""保留审查问题与看板卡片的来源关联。"""
import sqlalchemy as sa
from alembic import op

revision = "0019_review_issue_board"
down_revision = "0018_task_plans_and_inbox"
branch_labels = None
depends_on = None


def upgrade():
    # 全新安装的初始迁移会用当前模型建表，已有数据库才需要补列。
    if "board_task_id" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("review_issues")}:
        op.add_column("review_issues", sa.Column("board_task_id", sa.Integer()))
        op.create_foreign_key("review_issues_board_task_id_fkey", "review_issues", "board_tasks",
                              ["board_task_id"], ["id"], ondelete="SET NULL")
        op.create_unique_constraint("review_issues_board_task_id_key", "review_issues", ["board_task_id"])
    # 已有周明细或仍待接收的转交任务继续显示原审查来源。
    op.execute("""
        UPDATE review_issues r SET board_task_id = d.board_task_id
        FROM board_task_details d WHERE d.task_id = r.task_id
    """)
    op.execute("""
        UPDATE review_issues r SET board_task_id = b.id
        FROM board_tasks b WHERE r.board_task_id IS NULL
          AND b.handoff->>'review_issue_id' = CAST(r.id AS text)
    """)


def downgrade():
    op.drop_column("review_issues", "board_task_id")
