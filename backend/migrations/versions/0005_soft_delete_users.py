"""Keep deleted users and their historical data."""
from alembic import op
import sqlalchemy as sa

revision = "0005_soft_delete_users"
down_revision = "0004_account_lock"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "is_deleted" not in columns:
        op.add_column("users", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "is_deleted")
