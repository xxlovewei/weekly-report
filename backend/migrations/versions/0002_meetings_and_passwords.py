"""Meeting records, task group, and initial-password flag."""
from alembic import op
import sqlalchemy as sa

revision = "0002_meetings_and_passwords"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "must_change_password" not in {c["name"] for c in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "task_group" not in {c["name"] for c in inspector.get_columns("tasks")}:
        op.add_column("tasks", sa.Column("task_group", sa.String(length=200), nullable=False, server_default=""))
    if not inspector.has_table("meetings"):
        op.create_table("meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("meeting_type", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("needs_follow_up", sa.Boolean(), nullable=False),
    )
        op.create_index("ix_meetings_meeting_date", "meetings", ["meeting_date"])
    if not inspector.has_table("meeting_tasks"):
        op.create_table("meeting_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
    )
        op.create_index("ix_meeting_tasks_meeting_id", "meeting_tasks", ["meeting_id"])

def downgrade():
    op.drop_table("meeting_tasks")
    op.drop_table("meetings")
    op.drop_column("tasks", "task_group")
    op.drop_column("users", "must_change_password")
