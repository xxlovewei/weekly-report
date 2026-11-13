"""提交消息变更后，通知实时连接重新读取数据库。"""
from alembic import op

revision = "0011_notification_events"
down_revision = "0010_code_review"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION zhoubao_notify_message_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('zhoubao_messages', NEW.user_id::text);
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER zhoubao_message_change
        AFTER INSERT OR UPDATE OF is_read ON notifications
        FOR EACH ROW EXECUTE FUNCTION zhoubao_notify_message_change()
    """)


def downgrade():
    op.execute("DROP TRIGGER zhoubao_message_change ON notifications")
    op.execute("DROP FUNCTION zhoubao_notify_message_change()")
