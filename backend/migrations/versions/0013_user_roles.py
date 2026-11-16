"""将原有单角色迁移为角色列表。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0013_user_roles"
down_revision = "0012_review_project_common"
branch_labels = None
depends_on = None


def upgrade():
    # 全新安装由初始迁移按当前模型建表，已经使用角色列表。
    if "role" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}:
        return
    op.add_column("users", sa.Column("roles", ARRAY(sa.String(16)), nullable=False, server_default="{user}"))
    op.execute("UPDATE users SET roles = ARRAY[role]")
    op.create_check_constraint("ck_users_roles", "users", "roles IN ('{user}', '{admin}', '{admin,user}')")
    op.drop_column("users", "role")


def downgrade():
    # 回退到单角色时优先保留管理员权限。
    op.add_column("users", sa.Column("role", sa.String(16), nullable=True))
    op.execute("UPDATE users SET role = CASE WHEN 'admin' = ANY(roles) THEN 'admin' ELSE 'user' END")
    op.alter_column("users", "role", nullable=False)
    op.drop_column("users", "roles")
