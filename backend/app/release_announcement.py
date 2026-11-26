"""生产验证通过后显式发送版本通知，同版本只发布一次。"""
import argparse
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .db import SessionLocal
from .models import Notification, ReleaseRecord
from .notification_events import RELEASE_ANNOUNCED

VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$", re.ASCII)
RECOVERY_WINDOW = timedelta(minutes=10)


def announce_release(version: str) -> bool:
    with SessionLocal.begin() as db:
        updated = db.scalar(update(ReleaseRecord)
                            .where(ReleaseRecord.version == version, ReleaseRecord.announced_at.is_(None))
                            .values(announced_at=func.now()).returning(ReleaseRecord.id))
        if updated is None:
            if db.scalar(select(ReleaseRecord.id).where(ReleaseRecord.version == version)) is None:
                raise ValueError(f"版本 {version} 尚未入库")
            return False
        # 提交后唤醒在线消息流。仍运行旧版本的标签页重连后可从数据库补收。
        db.execute(text("SELECT pg_notify('zhoubao_messages', :event)"), {"event": RELEASE_ANNOUNCED})
        return True


def stream_release(db, user_id: int, client_version: str | None, legacy_reconnect: bool, connected_at: datetime):
    release = select(ReleaseRecord.version).where(ReleaseRecord.announced_at.is_not(None))
    if client_version is None:
        # 无法识别页面版本时，只在短时重连或当前连接期间补发普通消息。
        release = release.where(ReleaseRecord.announced_at >= datetime.now(timezone.utc) - RECOVERY_WINDOW)
        if not legacy_reconnect:
            release = release.where(ReleaseRecord.announced_at >= connected_at)
    version = db.scalar(release.order_by(ReleaseRecord.announced_at.desc(), ReleaseRecord.id.desc()).limit(1))
    if version is None:
        return None
    message = f"版本v{version}已更新🎉，请刷新页面🔄️体验吧"
    if client_version is not None:
        if tuple(map(int, client_version.split("."))) < tuple(map(int, version.split("."))):
            return {"version": version, "message": message}
        return None

    # 旧页面重连时带原有游标，通过它能识别的普通消息格式投递一次。
    key = f"release:{version}"
    exists = db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.event_key == key))
    if exists is None:
        db.execute(insert(Notification).values(user_id=user_id, event_key=key, kind="系统通知", title=message)
                   .on_conflict_do_nothing(index_elements=["user_id", "event_key"]))
        db.commit()
    return None


def main():
    parser = argparse.ArgumentParser(description="向在线用户发送已上线版本的刷新提醒")
    parser.add_argument("version", help="例如 2.3.1")
    args = parser.parse_args()
    if len(args.version) > 40 or not VERSION.fullmatch(args.version):
        parser.error("版本号必须采用 2.3.1 格式")
    try:
        sent = announce_release(args.version)
    except ValueError as error:
        parser.error(str(error))
    print(f"版本 v{args.version} 通知已发送" if sent else f"版本 v{args.version} 通知已发送过")


if __name__ == "__main__":
    main()
