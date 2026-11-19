from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import main
from .db import get_db
from .main import Input, active_session, finish, idempotent, lock_task_changes, validate_task_type, week_row
from .models import BoardTask, BoardTaskDetail, Task, Week

router = APIRouter(prefix="/api/board-tasks")


class CardInput(Input):
    name: str = Field(min_length=1, max_length=200)
    category_name: str = Field(min_length=1, max_length=100)
    priority: Literal["高", "中", "低"]


class CardMove(Input):
    state: Literal["inbox", "in_progress", "done"]
    revision: int = Field(ge=0)
    week_start: date


def board_detail(db: Session, card_id: int, week_id: int):
    return db.scalar(select(Task).join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                     .where(BoardTaskDetail.board_task_id == card_id, BoardTaskDetail.week_id == week_id))


def delete_detail(db: Session, detail: Task):
    week_id = detail.week_id
    db.delete(detail)
    db.flush()
    remaining = db.scalars(select(Task).where(Task.week_id == week_id).order_by(Task.position, Task.id))
    for position, task in enumerate(remaining, 1):
        task.position = position


def sync_card_from_detail(db: Session, week: Week, task_id: int, status: str | None, *, removed=False):
    link = db.get(BoardTaskDetail, task_id)
    if link is None:
        return
    card = db.get(BoardTask, link.board_task_id)
    if week.start_date == main.current_work_week():
        state = "done" if status == "已完成" else "in_progress" if status else "inbox"
        if removed or state != card.state:
            card.state = state
            card.revision += 1
    elif removed:
        # 删除历史关联可能解锁卡片编辑，通知使用旧版本的页面重新载入。
        card.revision += 1


def card_json(card: BoardTask, *, current=False, historical=False):
    return {"id": card.id, "name": card.name, "category_name": card.category_name, "priority": card.priority,
            "state": card.state, "revision": card.revision, "has_current_detail": current, "has_other_details": historical}


def detail_weeks(db: Session, card_id: int):
    return list(db.scalars(select(Week.start_date).join(BoardTaskDetail, BoardTaskDetail.week_id == Week.id)
                           .where(BoardTaskDetail.board_task_id == card_id)))


def checked_card(db: Session, user_id: int, card_id: int, revision: int, week_start: date, *, fields=False):
    card = db.get(BoardTask, card_id)
    if card is None or card.user_id != user_id:
        raise HTTPException(404, "看板任务不存在")
    if revision != card.revision or week_start != main.current_work_week():
        raise HTTPException(409, "卡片或当前周已更新，请重新载入后操作")
    historical = any(start != week_start for start in detail_weeks(db, card.id))
    if fields and historical:
        raise HTTPException(409, "卡片已关联其他周的任务明细，仅可移列或续做")
    return card, historical


@router.get("")
def list_cards(auth=Depends(active_session), db: Session = Depends(get_db)):
    start = main.current_work_week()
    # 一条查询读取卡片及其关联周，避免并发更新造成同一次响应内的数据不一致。
    rows = db.execute(select(BoardTask, Week.start_date)
                      .outerjoin(BoardTaskDetail, BoardTaskDetail.board_task_id == BoardTask.id)
                      .outerjoin(Week, Week.id == BoardTaskDetail.week_id)
                      .where(BoardTask.user_id == auth[0].id).order_by(BoardTask.id))
    cards = {}
    for card, linked_week in rows:
        payload = cards.setdefault(card.id, card_json(card))
        if linked_week == start:
            payload["has_current_detail"] = True
        elif linked_week is not None:
            payload["has_other_details"] = True
    return {"current_week": start.isoformat(), "tasks": list(cards.values())}


@router.post("", status_code=201)
def add_card(data: CardInput, key: str | None = Header(default=None, alias="Idempotency-Key"),
             auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    old = idempotent(db, owner, key, "board:add")
    if old is not None:
        return old
    validate_task_type(db, owner, data.category_name)
    card = BoardTask(user_id=owner, **data.model_dump())
    db.add(card)
    db.flush()
    return finish(db, owner, key, "board:add", card_json(card))


@router.patch("/{card_id}")
def edit_card(card_id: int, revision: int, week_start: date, data: CardInput,
              auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, _ = checked_card(db, owner, card_id, revision, week_start, fields=True)
    changes = {key: value for key, value in data.model_dump().items() if getattr(card, key) != value}
    if "category_name" in changes:
        validate_task_type(db, owner, changes["category_name"])
    week = week_row(db, owner, week_start)
    detail = board_detail(db, card.id, week.id) if week else None
    for key, value in changes.items():
        setattr(card, key, value)
        if detail:
            setattr(detail, "task_group" if key == "name" else key, value)
    if changes:
        card.revision += 1
        if detail:
            week.revision += 1
    db.commit()
    return card_json(card, current=detail is not None)


@router.post("/{card_id}/duplicate", status_code=201)
def duplicate_card(card_id: int, revision: int, week_start: date,
                   key: str | None = Header(default=None, alias="Idempotency-Key"),
                   auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    operation = f"board:duplicate:{card_id}"
    old = idempotent(db, owner, key, operation)
    if old is not None:
        return old
    source, _ = checked_card(db, owner, card_id, revision, week_start, fields=True)
    card = BoardTask(user_id=owner, name=source.name, category_name=source.category_name, priority=source.priority)
    db.add(card)
    db.flush()
    return finish(db, owner, key, operation, card_json(card))


@router.delete("/{card_id}")
def delete_card(card_id: int, revision: int, week_start: date, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, _ = checked_card(db, owner, card_id, revision, week_start, fields=True)
    week = week_row(db, owner, week_start)
    detail = board_detail(db, card.id, week.id) if week else None
    if detail:
        delete_detail(db, detail)
        week.revision += 1
    db.delete(card)
    db.commit()
    return {"ok": True}


def continued_status(db: Session, card_id: int, current_detail: Task | None):
    if current_detail:
        previous = current_detail.status
    else:
        previous = db.scalar(select(Task.status).join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                             .join(Week, Week.id == BoardTaskDetail.week_id)
                             .where(BoardTaskDetail.board_task_id == card_id).order_by(Week.start_date.desc()).limit(1))
    return previous if previous and previous.endswith("%") else "5%"


@router.patch("/{card_id}/status")
def move_card(card_id: int, data: CardMove, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, historical = checked_card(db, owner, card_id, data.revision, data.week_start)
    week = week_row(db, owner, data.week_start, create=data.state != "inbox")
    detail = board_detail(db, card.id, week.id) if week else None
    if data.state == "inbox":
        if detail and card.state != "inbox":
            delete_detail(db, detail)
            week.revision += 1
            detail = None
    else:
        status = "已完成" if data.state == "done" else continued_status(db, card.id, detail)
        if detail is None:
            position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
            detail = Task(week_id=week.id, position=position + 1, task_group=card.name,
                          category_name=card.category_name, priority=card.priority, status=status)
            db.add(detail)
            db.flush()
            db.add(BoardTaskDetail(task_id=detail.id, board_task_id=card.id, week_id=week.id))
            week.revision += 1
        elif detail.status != status:
            detail.status = status
            week.revision += 1
    card.state = data.state
    card.revision += 1
    db.commit()
    return card_json(card, current=detail is not None, historical=historical)
