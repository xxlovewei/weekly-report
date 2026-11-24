from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload

from . import main
from .db import get_db
from .main import Input, active_session, finish, idempotent, lock_task_changes, validate_task_type, week_row
from .models import BoardTask, BoardTaskDetail, Task, TaskPlan, Week

router = APIRouter(prefix="/api/board-tasks")


class CardInput(Input):
    name: str = Field(min_length=1, max_length=200)
    category_name: str = Field(min_length=1, max_length=100)
    priority: Literal["高", "中", "低"]
    notes: str = Field(default="", max_length=5000)

class CardUpdate(CardInput):
    name: str = Field(max_length=200)
    category_name: str = Field(max_length=100)

class CardNotesUpdate(Input):
    notes: str = Field(max_length=5000)


class CardMove(Input):
    state: Literal["inbox", "in_progress", "done"]
    revision: int = Field(ge=0)
    week_start: date


class CardPosition(Input):
    revision: int = Field(ge=0)
    week_start: date
    before_id: int | None = None


def column_cards(owner: int, state: str):
    return select(BoardTask).where(BoardTask.user_id == owner, BoardTask.state == state)


def position_at_edge(db: Session, owner: int, state: str, *, top: bool):
    edge = func.min(BoardTask.position) if top else func.max(BoardTask.position)
    current = db.scalar(column_cards(owner, state).with_only_columns(edge))
    return (0 if current is None else current) + (-1 if top else 1)


def put_at_top(db: Session, card: BoardTask, state: str):
    if card.state != state:
        card.position = position_at_edge(db, card.user_id, state, top=True)
        card.state = state
        # 只在状态转换时记录完成周，编辑和排序不会改写历史归属。
        card.completed_week = main.current_work_week() if state == "done" else None


def board_detail(db: Session, card_id: int, week_id: int):
    return db.scalar(select(Task).join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                     .where(BoardTaskDetail.board_task_id == card_id, BoardTaskDetail.week_id == week_id))

def linked_card(db: Session, task_id: int):
    link = db.get(BoardTaskDetail, task_id)
    return db.get(BoardTask, link.board_task_id) if link else None


def prior_detail_exists(card_id, current_week: date):
    detail = aliased(BoardTaskDetail)
    return (select(detail.task_id).join(Week, Week.id == detail.week_id)
            .where(detail.board_task_id == card_id, Week.start_date < current_week).exists())


def has_prior_detail(db: Session, card_id: int, current_week: date):
    return db.scalar(select(prior_detail_exists(card_id, current_week)))


def state_for_status(status: str | None):
    return "done" if status == "已完成" else "in_progress" if status else "inbox"


def create_card_for_detail(db: Session, week: Week, task: Task):
    # 新增和复制的明细各有一张独立任务箱卡片。
    card = add_inbox_card(db, week.user_id, name=task.task_group, category_name=task.category_name or "",
                          priority=task.priority or "低", notes=task.notes or "")
    db.add(task)
    db.flush()
    db.add(BoardTaskDetail(task_id=task.id, board_task_id=card.id, week_id=week.id))


def delete_detail(db: Session, detail: Task):
    week_id = detail.week_id
    db.delete(detail)
    db.flush()
    remaining = db.scalars(select(Task).where(Task.week_id == week_id).order_by(Task.position, Task.id))
    for position, task in enumerate(remaining, 1):
        task.position = position


def sync_card_from_detail(db: Session, card: BoardTask, task: Task | TaskPlan, fields):
    changed = False
    for field, attr, value in (
        ("task_group", "name", task.task_group),
        ("category_name", "category_name", task.category_name or ""),
        ("priority", "priority", task.priority or "低"),
        ("notes", "notes", task.notes),
    ):
        if field in fields and getattr(card, attr) != value:
            setattr(card, attr, value)
            changed = True
    if "status" in fields:
        state = state_for_status(task.status)
        changed |= state != card.state
        put_at_top(db, card, state)
        changed |= set_assignment_status(card, task.status)
    if changed:
        card.revision += 1


def percentage(status: str | None):
    return status if status and status.endswith("%") else None


def pending_progress(card: BoardTask):
    status = card.assignment_status if card.meeting_task_id else (card.handoff or {}).get("status")
    return percentage(status)


def card_json(card: BoardTask, *, current=False, historical=False, status: str | None = None):
    meeting = card.meeting_task.meeting if card.meeting_task else None
    status = (percentage(status) or "5%") if card.state == "in_progress" else "已完成" if card.state == "done" else None
    return {"id": card.id, "name": card.name, "category_name": card.category_name, "priority": card.priority, "notes": card.notes,
            "state": card.state, "status": status, "position": card.position, "revision": card.revision,
            "completed_week": card.completed_week.isoformat() if card.completed_week else None,
            "meeting_id": meeting.id if meeting else None, "transferred_by": card.transferred_by,
            "review_issue_id": card.review_issue.id if card.review_issue else None,
            "name_locked": bool(card.meeting_task and len(card.meeting_task.assignments) > 1),
            "has_current_detail": current, "has_other_details": historical}


def add_inbox_card(db: Session, owner: int, *, name: str, category_name="", priority="低", **details):
    card = BoardTask(user_id=owner, name=name, category_name=category_name, priority=priority,
                     position=position_at_edge(db, owner, "inbox", top=False), **details)
    db.add(card)
    db.flush()
    return card


def checked_card(db: Session, user_id: int, card_id: int, revision: int, week_start: date, *, fields=False):
    card = db.get(BoardTask, card_id)
    if card is None or card.user_id != user_id:
        raise HTTPException(404, "看板任务不存在")
    if revision != card.revision or week_start != main.current_work_week():
        raise HTTPException(409, "卡片或当前周已更新，请重新载入后操作")
    historical = has_prior_detail(db, card.id, week_start)
    if fields and historical:
        raise HTTPException(409, "卡片已关联其他周的任务明细，仅可移列或续做")
    return card, historical


@router.get("")
def list_cards(auth=Depends(active_session), db: Session = Depends(get_db)):
    start = main.current_work_week()
    main.apply_due_plans(db, auth[0].id, start)
    # 同时读取卡片和周明细，本周尚无明细时优先保留最近一次进度。
    rows = db.execute(select(BoardTask, Week.start_date, Task.status).options(joinedload(BoardTask.review_issue))
                      .outerjoin(BoardTaskDetail, BoardTaskDetail.board_task_id == BoardTask.id)
                      .outerjoin(Week, Week.id == BoardTaskDetail.week_id)
                      .outerjoin(Task, Task.id == BoardTaskDetail.task_id)
                      .where(BoardTask.user_id == auth[0].id)
                      .order_by(BoardTask.position, BoardTask.id, Week.start_date.desc().nulls_last()))
    cards = {}
    for card, linked_week, status in rows:
        if card.id not in cards:
            status = status if linked_week == start else pending_progress(card) or status
            cards[card.id] = card_json(card, status=status)
        payload = cards[card.id]
        if linked_week == start:
            payload["has_current_detail"] = True
        elif linked_week is not None and linked_week < start:
            payload["has_other_details"] = True
    db.commit()
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
    card = add_inbox_card(db, owner, **data.model_dump())
    return finish(db, owner, key, "board:add", card_json(card))


@router.patch("/{card_id}")
def edit_card(card_id: int, revision: int, week_start: date, data: CardUpdate | CardNotesUpdate,
              auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, historical = checked_card(db, owner, card_id, revision, week_start)
    changes = {key: value for key, value in data.model_dump(exclude_unset=True).items() if getattr(card, key) != value}
    if historical and not isinstance(data, CardNotesUpdate):
        raise HTTPException(409, "卡片已关联其他周的任务明细，仅可修改备注、移列或续做")
    if "name" in changes and not changes["name"]:
        raise HTTPException(422, "请输入任务名称")
    if "category_name" in changes:
        validate_task_type(db, owner, changes["category_name"])
    week = week_row(db, owner, week_start)
    detail = board_detail(db, card.id, week.id) if week else None
    meeting_rename = card.meeting_task is not None and "name" in changes
    if meeting_rename:
        if len(card.meeting_task.assignments) > 1:
            raise HTTPException(409, "多人会议任务的名称请在会议记录中修改")
        main.rename_meeting_task(db, card.meeting_task, changes["name"], skip_week_id=week.id if week else None)
    for key, value in changes.items():
        setattr(card, key, value)
        if detail:
            setattr(detail, "task_group" if key == "name" else key, value)
    if changes:
        if not meeting_rename:
            card.revision += 1
        if detail:
            week.revision += 1
    db.commit()
    status = detail.status if detail else pending_progress(card) or latest_detail_status(db, card)
    return card_json(card, current=detail is not None, historical=historical, status=status)


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
    card = add_inbox_card(db, owner, name=source.name, category_name=source.category_name,
                          priority=source.priority, notes=source.notes)
    return finish(db, owner, key, operation, card_json(card))


@router.delete("/{card_id}")
def delete_card(card_id: int, revision: int, week_start: date, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, _ = checked_card(db, owner, card_id, revision, week_start, fields=True)
    if card.meeting_task_id:
        raise HTTPException(403, "会议指派任务不可删除，请在会议记录中取消指派")
    week = week_row(db, owner, week_start)
    detail = board_detail(db, card.id, week.id) if week else None
    if detail:
        delete_detail(db, detail)
        week.revision += 1
    db.delete(card)
    db.commit()
    return {"ok": True}


def progress_status(db: Session, card: BoardTask, detail: Task | None = None):
    if detail is not None:
        return percentage(detail.status) or "5%"
    if status := pending_progress(card):
        return status
    return percentage(latest_detail_status(db, card)) or "5%"


def latest_detail_status(db: Session, card: BoardTask, *, before: date | None = None):
    query = (select(Task.status).join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
             .join(Week, Week.id == BoardTaskDetail.week_id)
             .where(BoardTaskDetail.board_task_id == card.id))
    if before is not None:
        query = query.where(Week.start_date < before)
    return db.scalar(query.order_by(Week.start_date.desc()).limit(1))


def set_assignment_status(card: BoardTask, status: str | None):
    if card.meeting_task and card.assignment_status != status:
        card.assignment_status = status
        card.meeting_task.meeting.revision += 1
        return True
    return False


def attach_detail(db: Session, card: BoardTask, week: Week, position: int, status: str | None, *,
                  description: str | None = None, current: bool = True):
    handoff = card.handoff or {}
    issue = card.review_issue
    if description is None:
        description = handoff.get("description", issue.title if issue else "")
    detail = Task(week_id=week.id, position=position, task_group=card.name,
                  category_name=card.category_name or None, priority=card.priority, status=status,
                  meeting_task_id=card.meeting_task_id, transferred_by=card.transferred_by,
                  description=description, notes=card.notes,
                  work_days=handoff.get("work_days", []))
    db.add(detail)
    db.flush()
    db.add(BoardTaskDetail(task_id=detail.id, board_task_id=card.id, week_id=week.id))
    if current:
        if issue:
            issue.task_id = detail.id
            issue.status = status
        card.handoff = None
    return detail


def cards_missing_from_week(db: Session, owner: int, week: Week | None):
    query = column_cards(owner, "in_progress").order_by(BoardTask.position, BoardTask.id)
    if week:
        query = query.where(~select(BoardTaskDetail.task_id).where(
            BoardTaskDetail.board_task_id == BoardTask.id, BoardTaskDetail.week_id == week.id).exists())
    return list(db.scalars(query))


@router.patch("/{card_id}/position")
def reorder_card(card_id: int, data: CardPosition, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    card, _ = checked_card(db, owner, card_id, data.revision, data.week_start)
    ordered = list(db.scalars(column_cards(owner, card.state).order_by(BoardTask.position, BoardTask.id)))
    peers = [item for item in ordered if item.id != card.id]
    index = next((index for index, item in enumerate(peers) if item.id == data.before_id), None)
    if data.before_id is not None and index is None:
        raise HTTPException(409, "目标卡片已变化，请重新载入后排序")
    peers.insert(len(peers) if index is None else index, card)
    if peers != ordered:
        # 只调整看板顺序，不触碰每周任务明细。以当前列为准处理并发排序。
        for position, item in enumerate(peers):
            item.position = position
        card.revision += 1
    db.commit()
    return [{"id": item.id, "position": item.position, "revision": item.revision} for item in peers]


@router.patch("/{card_id}/status")
def move_card(card_id: int, data: CardMove, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = auth[0].id
    lock_task_changes(db)
    main.apply_due_plans(db, owner, main.current_work_week())
    card, historical = checked_card(db, owner, card_id, data.revision, data.week_start)
    week = week_row(db, owner, data.week_start, create=data.state != "inbox")
    detail = board_detail(db, card.id, week.id) if week else None
    if data.state == "inbox":
        if detail and card.state != "inbox":
            delete_detail(db, detail)
            week.revision += 1
            detail = None
            if card.review_issue:
                card.review_issue.status = None
    else:
        status = "已完成" if data.state == "done" else progress_status(db, card, detail)
        if detail is None:
            position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
            detail = attach_detail(db, card, week, position + 1, status)
            week.revision += 1
        elif detail.status != status:
            detail.status = status
            week.revision += 1
            if card.review_issue:
                card.review_issue.status = status
        set_assignment_status(card, status)
    put_at_top(db, card, data.state)
    card.revision += 1
    db.commit()
    return card_json(card, current=detail is not None, historical=historical, status=detail.status if detail else None)
