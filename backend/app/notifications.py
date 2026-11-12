from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .main import Input, active_session
from .models import Notification, Task, User, Week

router = APIRouter(prefix="/api/notifications")
SHANGHAI = timezone(timedelta(hours=8))


@router.get("/unread")
def unread_count(auth=Depends(active_session), db: Session = Depends(get_db)):
    return {"count": db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == auth[0].id, Notification.is_read.is_(False),
    ))}


@router.get("")
def list_notifications(
    all_users: bool = False, day: date | None = None, is_read: bool | None = None,
    kind: Literal["转交任务", "代码审查"] | None = None, page: int = Query(1, ge=1, le=1000000),
    auth=Depends(active_session), db: Session = Depends(get_db),
):
    user = auth[0]
    if all_users and user.role != "admin":
        raise HTTPException(403, "仅管理员可查看所有人员的消息")
    filters = []
    if not all_users:
        filters.append(Notification.user_id == user.id)
    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=SHANGHAI)
        filters.extend((Notification.created_at >= start, Notification.created_at < start + timedelta(days=1)))
    if kind is not None:
        filters.append(Notification.kind == kind)
    if is_read is not None:
        filters.append(Notification.is_read.is_(is_read))
    rows = db.execute(select(Notification, User.display_name, Week.start_date, Week.user_id)
                      .join(User, User.id == Notification.user_id)
                      .outerjoin(Task, Task.id == Notification.task_id)
                      .outerjoin(Week, Week.id == Task.week_id)
                      .where(*filters).order_by(Notification.created_at.desc(), Notification.id.desc())
                      .limit(20).offset((page - 1) * 20))
    items = []
    for row, recipient, week, owner_id in rows:
        item = {"id": row.id, "kind": row.kind, "title": row.title, "is_read": row.is_read, "created_at": row.created_at}
        if all_users:
            item["recipient"] = recipient
        elif row.review_date:
            item["target"] = {"date": row.review_date}
        elif week and owner_id == user.id:
            item["target"] = {"week": week, "task": row.task_id}
        items.append(item)
    return {"items": items, "total": db.scalar(select(func.count()).select_from(Notification).where(*filters))}


class ReadInput(Input):
    is_read: bool


@router.patch("/{message_id}")
def mark_read(message_id: int, data: ReadInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = db.get(Notification, message_id)
    if not row or row.user_id != auth[0].id:
        raise HTTPException(404, "消息不存在")
    row.is_read = data.is_read
    db.commit()
    return {"ok": True}
