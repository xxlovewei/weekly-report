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
DESKTOP_RELEASE_VERSION = (2, 4, 2)


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


def version_number(version):
    return tuple(map(int, version.split(".")))


def stream_release(db, user_id: int, client_version: str | None, legacy_reconnect: bool, connected_at: datetime):
    cutoff = datetime.now(timezone.utc) - RECOVERY_WINDOW
    release = select(ReleaseRecord.version, ReleaseRecord.announced_at).where(ReleaseRecord.announced_at.is_not(None))
    if client_version is None:
        # 无法识别页面版本时，只在短时重连或当前连接期间补发普通消息。
        release = release.where(ReleaseRecord.announced_at >= cutoff)
        if not legacy_reconnect:
            release = release.where(ReleaseRecord.announced_at >= connected_at)
    row = db.execute(release.order_by(ReleaseRecord.announced_at.desc(), ReleaseRecord.id.desc()).limit(1)).first()
    if row is None:
        return None
    version, announced_at = row
    message = f"版本v{version}已更新🎉，请刷新页面🔄️体验吧"
    if client_version is not None:
        client = version_number(client_version)
        target = version_number(version)
        if client >= target:
            return None
        # 首次上线时，已打开的旧页签通过现有系统消息获得桌面提醒。
        if client < DESKTOP_RELEASE_VERSION <= target and announced_at >= cutoff:
            save_legacy_notice(db, user_id, version, message)
        return {"version": version, "message": message}
    save_legacy_notice(db, user_id, version, message)
    return None


def save_legacy_notice(db, user_id, version, message):
    # 旧页签重复连接时，同一账号、同一版本只落一条系统消息。
    key = f"release:{version}"
    exists = db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.event_key == key))
    if exists is None:
        db.execute(insert(Notification).values(user_id=user_id, event_key=key, kind="系统通知", title=message)
                   .on_conflict_do_nothing(index_elements=["user_id", "event_key"]))
        db.commit()


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
