"""Track meeting creators and all distinct updaters."""
from alembic import op
import sqlalchemy as sa

revision = "0003_meeting_people"
down_revision = "0002_meetings_and_passwords"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "creator_id" not in {c["name"] for c in inspector.get_columns("meetings")}:
        op.add_column("meetings", sa.Column("creator_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_meetings_creator_id", "meetings", "users", ["creator_id"], ["id"])
    if not inspector.has_table("meeting_updaters"):
        op.create_table("meeting_updaters",
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        )

def downgrade():
    op.drop_table("meeting_updaters")
    op.drop_constraint("fk_meetings_creator_id", "meetings", type_="foreignkey")
    op.drop_column("meetings", "creator_id")
