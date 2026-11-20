from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

# 先加载现有测试夹具，使应用只连接隔离测试库。
from tests.test_api import clean_db
from app.db import SessionLocal
from app.models import Notification, ReleaseRecord, User
from app.notifications import stream_snapshot
from app.release_announcement import announce_release


def test_release_announces_only_after_confirmation_and_legacy_delivery_is_idempotent(monkeypatch):
    message = "版本v2.3.1已更新🎉，请刷新页面🔄️体验吧"
    with SessionLocal() as db:
        db.add(ReleaseRecord(version="2.3.1", description="更新说明"))
        db.commit()
    monkeypatch.setattr("app.notifications.active_session", lambda request, db: (request, None))
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.id)).all()
    active, connected, offline = users
    opened_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    def snapshot(user, version, cursor=0, reconnect=False, connected_at=opened_at):
        return stream_snapshot(user, user.id, cursor, version, reconnect, connected_at)

    assert snapshot(active, "2.3.0")["release"] is None
    with pytest.raises(ValueError):
        announce_release("2.3.2")
    assert announce_release("2.3.1")
    assert not announce_release("2.3.1")
    assert snapshot(active, "2.3.0")["release"] == {
        "version": "2.3.1", "message": message,
    }
    assert snapshot(active, "2.3.1")["release"] is None
    assert snapshot(offline, None, cursor=None, connected_at=datetime.now(timezone.utc))["messages"] == []
    legacy = snapshot(active, None, reconnect=True)
    assert legacy["messages"][0]["title"] == message
    assert snapshot(active, None, cursor=legacy["cursor"], reconnect=True)["messages"] == []
    assert snapshot(connected, None, cursor=None)["messages"][0]["title"] == message
    with SessionLocal() as db:
        assert set(db.scalars(select(Notification.user_id))) == {active.id, connected.id}
        record = db.scalar(select(ReleaseRecord))
        record.announced_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    assert snapshot(active, "2.3.0")["release"] is None
