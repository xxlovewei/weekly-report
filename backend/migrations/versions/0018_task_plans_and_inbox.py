"""新增任务计划，并将已有指派和转交消息关联到任务看板。"""
import sqlalchemy as sa
from alembic import op

revision = "0018_task_plans_and_inbox"
down_revision = "0017_release_announcement"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    if not sa.inspect(db).has_table("task_plans"):
        op.create_table(
            "task_plans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("week_id", sa.Integer(), sa.ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("applied", sa.Boolean(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("category_name", sa.String(100)),
            sa.Column("task_group", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16)),
            sa.Column("priority", sa.String(4)),
            sa.Column("work_days", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            comment="任务计划表",
        )
        op.create_index("ix_task_plans_week_id", "task_plans", ["week_id"])
    columns = {column["name"] for column in sa.inspect(db).get_columns("board_tasks")}
    if "meeting_task_id" not in columns:
        op.add_column("board_tasks", sa.Column("meeting_task_id", sa.Integer()))
        op.create_foreign_key("board_tasks_meeting_task_id_fkey", "board_tasks", "meeting_tasks",
                              ["meeting_task_id"], ["id"], ondelete="CASCADE")
        op.create_unique_constraint("uq_board_meeting_assignee", "board_tasks", ["meeting_task_id", "user_id"])
        op.add_column("board_tasks", sa.Column("assignment_status", sa.String(16)))
        op.add_column("board_tasks", sa.Column("transferred_by", sa.String(120)))
        op.add_column("board_tasks", sa.Column("handoff", sa.JSON()))
    if "board_task_id" not in {column["name"] for column in sa.inspect(db).get_columns("notifications")}:
        op.add_column("notifications", sa.Column("board_task_id", sa.Integer()))
        op.create_foreign_key("notifications_board_task_id_fkey", "notifications", "board_tasks",
                              ["board_task_id"], ["id"], ondelete="SET NULL")
    # 保留已存在的周明细，并为仍可访问的旧通知补齐看板入口。
    op.execute(sa.text("""
        CREATE TEMP TABLE migrated_task_cards ON COMMIT DROP AS
        SELECT t.id AS task_id, t.week_id, w.user_id, t.meeting_task_id, t.status, t.transferred_by,
               COALESCE(NULLIF(t.task_group, ''), LEFT(m.name, 200), NULLIF(LEFT(t.description, 200), ''), '未命名任务') AS name,
               COALESCE(t.category_name, '') AS category_name, COALESCE(t.priority, '低') AS priority,
               CASE WHEN t.status = '已完成' THEN 'done' WHEN right(t.status, 1) = '%' THEN 'in_progress'
                    ELSE 'inbox' END AS state,
               COALESCE(d.board_task_id, nextval(pg_get_serial_sequence('board_tasks', 'id'))) AS card_id,
               d.board_task_id IS NULL AS new_card
        FROM tasks t JOIN weeks w ON w.id = t.week_id
        LEFT JOIN meeting_tasks m ON m.id = t.meeting_task_id
        LEFT JOIN board_task_details d ON d.task_id = t.id
        WHERE t.meeting_task_id IS NOT NULL OR t.transferred_by IS NOT NULL
    """))
    op.execute(sa.text("""
        INSERT INTO board_tasks (id, user_id, name, category_name, priority, state, position, revision,
                                 meeting_task_id, assignment_status, transferred_by)
        SELECT card_id, user_id, name, category_name, priority, state, card_id, 0,
               meeting_task_id, CASE WHEN meeting_task_id IS NOT NULL THEN status END, transferred_by
        FROM migrated_task_cards WHERE new_card
    """))
    op.execute(sa.text("""
        INSERT INTO board_task_details (task_id, board_task_id, week_id)
        SELECT task_id, card_id, week_id FROM migrated_task_cards WHERE new_card
    """))
    op.execute(sa.text("""
        UPDATE board_tasks b SET meeting_task_id = m.meeting_task_id,
            assignment_status = CASE WHEN m.meeting_task_id IS NOT NULL THEN m.status END,
            transferred_by = m.transferred_by
        FROM migrated_task_cards m WHERE b.id = m.card_id AND NOT m.new_card
    """))
    op.execute(sa.text("""
        UPDATE notifications n SET board_task_id = m.card_id
        FROM migrated_task_cards m
        WHERE n.task_id = m.task_id AND n.user_id = m.user_id AND n.kind IN ('会议指派', '转交任务')
    """))


def downgrade():
    op.drop_column("notifications", "board_task_id")
    for column in ("handoff", "transferred_by", "assignment_status", "meeting_task_id"):
        op.drop_column("board_tasks", column)
    op.drop_table("task_plans")
