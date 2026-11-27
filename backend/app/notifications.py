import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db import SessionLocal, get_db
from .deploy_models import DeploymentItem
from .main import Input, active_session
from .models import BoardTask, Notification, User
from .notification_events import notification_lifespan, subscribers
from .release_announcement import DESKTOP_RELEASE_VERSION, VERSION, stream_release, version_number
from .scheduled_tasks import UNREAD_REMINDER, task_settings

router = APIRouter(prefix="/api/notifications", lifespan=notification_lifespan)
SHANGHAI = timezone(timedelta(hours=8))


@router.get("/unread")
def unread_count(auth=Depends(active_session), db: Session = Depends(get_db)):
    return {"count": count_unread(db, auth[0].id)}


def count_unread(db, user_id):
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.is_read.is_(False),
    ))


def notification_target(row, board_owner, plan_id, user_id):
    if row.review_date:
        return {"date": row.review_date}
    if board_owner == user_id:
        target = {"board_task": row.board_task_id}
        # 发版检查直接打开计划，保留任务编号供旧客户端跳转看板。
        if row.kind == "发版检查" and plan_id is not None:
            target["deployment_plan"] = plan_id
        return target
    return None


def stream_snapshot(request, user_id, cursor, client_version, legacy_reconnect, connected_at):
    with SessionLocal() as db:
        try:
            user, _ = active_session(request, db)
        except HTTPException:
            return None
        if user.id != user_id:
            return None
        if cursor is None:
            cursor = db.scalar(select(func.max(Notification.id)).where(Notification.user_id == user.id)) or 0
        release = stream_release(db, user_id, client_version, legacy_reconnect, connected_at)
        query = (select(Notification, BoardTask.user_id, DeploymentItem.plan_id)
                 .outerjoin(BoardTask, BoardTask.id == Notification.board_task_id)
                 .outerjoin(DeploymentItem, DeploymentItem.card_id == BoardTask.id)
                 .where(Notification.user_id == user_id, Notification.id > cursor))
        if client_version is not None and version_number(client_version) >= DESKTOP_RELEASE_VERSION:
            query = query.where(or_(Notification.event_key.is_(None), ~Notification.event_key.startswith("release:")))
        rows = db.execute(query.order_by(Notification.id).limit(100)).all()
        messages = [{"id": row.id, "kind": row.kind, "title": row.title, "is_read": row.is_read,
                     "target": notification_target(row, board_owner, plan_id, user_id)}
                    for row, board_owner, plan_id in rows]
        return {"count": count_unread(db, user_id), "messages": messages,
                "release": release,
                "unread_reminder": task_settings(db, UNREAD_REMINDER).model_dump(),
                "cursor": messages[-1]["id"] if messages else cursor}


@router.get("/stream")
async def notification_stream(request: Request, last_event_id: str = Header(default=""),
                              client_version: str | None = Query(default=None, max_length=40, pattern=VERSION.pattern)):
    def authenticate():
        with SessionLocal() as db:
            user, _ = active_session(request, db)
            return user.id, user.has_role("admin")

    user_id, admin = await run_in_threadpool(authenticate)
    cursor = int(last_event_id) if last_event_id.isascii() and last_event_id.isdigit() and len(last_event_id) < 16 else None
    legacy_reconnect = client_version is None and cursor is not None
    connected_at = datetime.now(timezone.utc)

    async def events():
        nonlocal cursor
        changed = asyncio.Event()
        subscribers[changed] = (user_id, admin)
        try:
            await request.app.state.notifications_ready.wait()
            previous_count = None
            previous_schedule = None
            previous_release = None
            invalidate = True
            while True:
                changed.clear()
                snapshot = await run_in_threadpool(
                    stream_snapshot, request, user_id, cursor, client_version, legacy_reconnect, connected_at,
                )
                if snapshot is None:
                    yield "event: session-ended\ndata: {}\n\n"
                    return
                cursor = snapshot["cursor"]
                if (invalidate or snapshot["messages"] or previous_count != snapshot["count"]
                        or previous_schedule != snapshot["unread_reminder"] or previous_release != snapshot["release"]):
                    yield f"id: {cursor}\ndata: {json.dumps(jsonable_encoder(snapshot), ensure_ascii=False)}\n\n"
                else:
                    yield ": heartbeat\n\n"
                previous_count = snapshot["count"]
                previous_schedule = snapshot["unread_reminder"]
                previous_release = snapshot["release"]
                if len(snapshot["messages"]) == 100:
                    continue
                try:
                    await asyncio.wait_for(changed.wait(), timeout=15)
                    invalidate = True
                except TimeoutError:
                    # 心跳同时重新核对权限及短暂断线期间的消息。
                    invalidate = changed.is_set()
        finally:
            subscribers.pop(changed, None)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })


@router.get("")
def list_notifications(
    all_users: bool = False, day: date | None = None, is_read: bool | None = None,
    kind: Literal["转交任务", "会议指派", "代码审查", "系统通知", "发版检查"] | None = None, page: int = Query(1, ge=1, le=1000000),
    auth=Depends(active_session), db: Session = Depends(get_db),
):
    user = auth[0]
    if all_users and not user.has_role("admin"):
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
    rows = db.execute(select(Notification, User.display_name, BoardTask.user_id, DeploymentItem.plan_id)
                      .join(User, User.id == Notification.user_id)
                      .outerjoin(BoardTask, BoardTask.id == Notification.board_task_id)
                      .outerjoin(DeploymentItem, DeploymentItem.card_id == BoardTask.id)
                      .where(*filters).order_by(Notification.created_at.desc(), Notification.id.desc())
                      .limit(20).offset((page - 1) * 20))
    items = []
    for row, recipient, board_owner, plan_id in rows:
        item = {"id": row.id, "kind": row.kind, "title": row.title, "is_read": row.is_read, "created_at": row.created_at}
        if all_users:
            item["recipient"] = recipient
        elif target := notification_target(row, board_owner, plan_id, user.id):
            item["target"] = target
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
