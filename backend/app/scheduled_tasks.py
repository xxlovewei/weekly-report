from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StrictBool
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import get_db
from .main import Input, admin
from .models import ScheduledTask
from .notification_events import SCHEDULE_CHANGED

router = APIRouter(prefix="/api/scheduled-tasks", dependencies=[Depends(admin)])
UNREAD_REMINDER = "unread-message-reminder"
TASK_NAMES = {UNREAD_REMINDER: "未读消息提醒"}


class ScheduleSettings(Input):
    enabled: StrictBool
    interval_minutes: int = Field(strict=True, ge=1, le=1440)


def task_settings(db: Session, key: str) -> ScheduleSettings:
    row = db.get(ScheduledTask, key)
    # 首次保存前沿用原有的五分钟提醒行为。
    if row is None:
        return ScheduleSettings(enabled=True, interval_minutes=5)
    return ScheduleSettings(enabled=row.enabled, interval_minutes=row.interval_minutes)


@router.get("")
def list_scheduled_tasks(db: Session = Depends(get_db)):
    return [{"key": key, "name": name, **task_settings(db, key).model_dump()}
            for key, name in TASK_NAMES.items()]


@router.put("/{key}")
def update_scheduled_task(key: str, settings: ScheduleSettings, db: Session = Depends(get_db)):
    if key not in TASK_NAMES:
        raise HTTPException(404, "定时任务不存在")
    values = settings.model_dump()
    statement = insert(ScheduledTask).values(key=key, **values)
    db.execute(statement.on_conflict_do_update(index_elements=[ScheduledTask.key], set_=values))
    # 提交后唤醒所有在线用户的消息流，使页面重新安排下一次扫描。
    db.execute(text("SELECT pg_notify('zhoubao_messages', :event)"), {"event": SCHEDULE_CHANGED})
    db.commit()
    return {"key": key, "name": TASK_NAMES[key], **values}
