"""Persist account status and rolling failed login attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0004_account_lock"
down_revision = "0003_meeting_people"
branch_labels = None
depends_on = None


def upgrade():
    # Initial migration creates current metadata on fresh installations.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "status" not in columns:
        op.add_column("users", sa.Column("status", sa.String(16), nullable=False, server_default="正常"))
    if "failed_login_times" not in columns:
        op.add_column("users", sa.Column("failed_login_times", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("users", "failed_login_times")
    op.drop_column("users", "status")
