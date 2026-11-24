from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import main
from .db import get_db
from .models import BoardTask, Task, TaskPlan, Week
from .task_board import (add_inbox_card, attach_detail, board_detail, column_cards, latest_detail_status,
                         progress_status, sync_card_from_detail)

router = APIRouter(prefix="/api/weeks/{week_start}/plans")


def plans_for_week(db: Session, week_id: int):
    return select(TaskPlan).where(TaskPlan.week_id == week_id).order_by(TaskPlan.position, TaskPlan.id)


def plan_rows(db: Session, week):
    return [{**main.task_fields_json(plan), "board_task_id": plan.board_task_id}
            for plan in db.scalars(plans_for_week(db, week.id))] if week else []


def apply_due_plans(db: Session, owner: int, through: date):
    current = main.current_work_week()
    pending = (select(TaskPlan).join(Week, Week.id == TaskPlan.week_id)
               .where(Week.user_id == owner, Week.start_date <= min(current, through), TaskPlan.applied.is_(False))
               .order_by(Week.start_date, TaskPlan.position, TaskPlan.id))
    if db.scalar(pending.with_only_columns(TaskPlan.id).limit(1)) is None:
        return
    main.lock_task_changes(db)
    plans = list(db.scalars(pending))
    positions = {}
    for plan in plans:
        week = db.get(Week, plan.week_id)
        if week.id not in positions:
            db.refresh(week)
            week.revision += 1
            positions[week.id] = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
        card = card_for_plan(db, week, plan)
        detail = board_detail(db, card.id, week.id)
        if detail is None:
            # 计划状态仅用于计划。到期时从之前最近的明细继承实际状态。
            status = latest_detail_status(db, card, before=week.start_date)
            positions[week.id] += 1
            is_current = week.start_date == current
            if is_current and card.pending_status:
                status = card.pending_status
            if is_current and plan.notes:
                card.notes = plan.notes
            detail = attach_detail(db, card, week, positions[week.id], status, description=plan.description,
                                   current=is_current)
            detail.work_days = list(plan.work_days)
            if plan.notes:
                detail.notes = plan.notes
            card.revision += 1
        elif not detail.description:
            detail.description = plan.description
        plan.applied = True
    db.flush()


def card_for_plan(db: Session, week: Week, plan: TaskPlan):
    card = db.get(BoardTask, plan.board_task_id) if plan.board_task_id else None
    if card is None:
        card = add_inbox_card(db, week.user_id, name=plan.task_group or "", category_name=plan.category_name or "",
                              priority=plan.priority or "低")
        plan.board_task_id = card.id
    return card


def check_plan_week(db, week_start):
    main.lock_task_changes(db)
    start = main.monday(week_start)
    if start != main.current_work_week() + timedelta(days=7):
        raise HTTPException(403, "仅下一周的任务计划可修改，计划到期后自动转为只读历史")
    return start


def checked_plan(db, actor, week_start, revision, plan_id=None):
    start = check_plan_week(db, week_start)
    week = main.week_row(db, actor.id, start, create=True)
    main.bump(db, week, revision)
    plan = db.get(TaskPlan, plan_id) if plan_id is not None else None
    if plan_id is not None and (plan is None or plan.week_id != week.id):
        raise HTTPException(404, "任务计划不存在")
    return week, plan


def shift_plans_down(db: Session, week: Week):
    db.execute(update(TaskPlan).where(TaskPlan.week_id == week.id).values(position=TaskPlan.position + 1))


def add_card_plan(db: Session, week: Week, card: BoardTask, position: int):
    # 复用原卡片，任务进展和工作日期留给下周计划填写。
    status = progress_status(db, card) if card.state == "in_progress" else None
    db.add(TaskPlan(week_id=week.id, board_task_id=card.id, position=position, task_group=card.name,
                    category_name=card.category_name or None, priority=card.priority, status=status))


@router.post("", status_code=201)
def add_plan(week_start: str, revision: int, idempotency_key: str | None = Header(default=None),
             auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    actor = auth[0]
    check_plan_week(db, week_start)
    operation = f"plan:add:{week_start}"
    old = main.idempotent(db, actor.id, idempotency_key, operation)
    if old is not None:
        return old
    week, _ = checked_plan(db, actor, week_start, revision)
    shift_plans_down(db, week)
    card = add_inbox_card(db, actor.id, name="")
    db.add(TaskPlan(week_id=week.id, position=1, board_task_id=card.id))
    db.flush()
    return main.finish(db, actor.id, idempotency_key, operation, main.work_week_json(db, week))


@router.post("/add-in-progress")
def copy_in_progress(week_start: str, revision: int, idempotency_key: str | None = Header(default=None),
                     auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    start = check_plan_week(db, week_start)
    owner = auth[0].id
    operation = f"plan:copy-in-progress:{week_start}"
    old = main.idempotent(db, owner, idempotency_key, operation)
    if old is not None:
        return old
    week = main.week_row(db, owner, start)
    cards = column_cards(owner, "in_progress").order_by(BoardTask.position, BoardTask.id)
    if week:
        cards = cards.where(~select(TaskPlan.id).where(
            TaskPlan.week_id == week.id, TaskPlan.board_task_id == BoardTask.id).exists())
    sources = list(db.scalars(cards))
    if not sources:
        return {**main.work_week_json(db, week), "no_source": True}
    week, _ = checked_plan(db, auth[0], week_start, revision)
    last_position = db.scalar(select(func.max(TaskPlan.position)).where(TaskPlan.week_id == week.id)) or 0
    for position, card in enumerate(sources, last_position + 1):
        add_card_plan(db, week, card, position)
    return main.finish(db, owner, idempotency_key, operation, main.work_week_json(db, week))


@router.post("/from-board/{card_id}", status_code=201)
def add_plan_from_board(week_start: str, card_id: int, revision: int,
                        idempotency_key: str | None = Header(default=None),
                        auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    start = check_plan_week(db, week_start)
    owner = auth[0].id
    operation = f"plan:from-board:{week_start}:{card_id}"
    old = main.idempotent(db, owner, idempotency_key, operation)
    if old is not None:
        return old
    card = db.get(BoardTask, card_id)
    if card is None or card.user_id != owner or card.state not in ("inbox", "in_progress"):
        raise HTTPException(404, "该任务已不在你的任务箱或进行中栏目")
    week = main.week_row(db, owner, start)
    # 与批量复制共用事务锁，同一张卡片在同一周只添加一次。
    if week and db.scalar(select(TaskPlan.id).where(TaskPlan.week_id == week.id, TaskPlan.board_task_id == card.id)):
        return main.work_week_json(db, week)
    week, _ = checked_plan(db, auth[0], week_start, revision)
    # 单张看板卡片加入时排在第一行，保留已有计划的相对顺序。
    shift_plans_down(db, week)
    add_card_plan(db, week, card, position=1)
    return main.finish(db, owner, idempotency_key, operation, main.work_week_json(db, week))


@router.put("/order")
def reorder_plans(week_start: str, revision: int, data: main.TaskOrderInput,
                  auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    week, _ = checked_plan(db, auth[0], week_start, revision)
    plans = {plan.id: plan for plan in db.scalars(plans_for_week(db, week.id))}
    if len(data.task_ids) != len(plans) or set(data.task_ids) != plans.keys():
        raise HTTPException(422, "排序必须包含本周全部任务计划，且不能重复")
    for position, plan_id in enumerate(data.task_ids, 1):
        plans[plan_id].position = position
    payload = main.work_week_json(db, week)
    db.commit()
    return payload


@router.patch("/{plan_id}")
def edit_plan(week_start: str, plan_id: int, revision: int, data: main.TaskPatch,
              auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    week, plan = checked_plan(db, auth[0], week_start, revision, plan_id)
    values = main.task_patch_values(db, week.user_id, data)
    shared = {field: values[field] for field in values.keys() & {"task_group", "category_name", "priority"}
              if getattr(plan, field) != values[field]}
    for field, value in values.items():
        setattr(plan, field, value)
    if shared:
        card = card_for_plan(db, week, plan)
        current_week = main.week_row(db, week.user_id, main.current_work_week())
        detail = board_detail(db, card.id, current_week.id) if current_week else None
        if "task_group" in shared and card.meeting_task and card.name != plan.task_group:
            if len(card.meeting_task.assignments) > 1:
                raise HTTPException(409, "多人会议任务的名称请在会议记录中修改")
            main.rename_meeting_task(db, card.meeting_task, plan.task_group,
                                     skip_week_id=current_week.id if current_week else None)
        # 计划状态、进展和工作日期保存在计划中，共享字段同步至卡片和当周明细。
        sync_card_from_detail(db, card, plan, shared.keys())
        if detail and any(getattr(detail, field) != value for field, value in shared.items()):
            for field, value in shared.items():
                setattr(detail, field, value)
            current_week.revision += 1
    payload = main.work_week_json(db, week)
    db.commit()
    return payload


@router.delete("/{plan_id}")
def delete_plan(week_start: str, plan_id: int, revision: int,
                auth=Depends(main.self_work_write), db: Session = Depends(get_db)):
    week, plan = checked_plan(db, auth[0], week_start, revision, plan_id)
    db.delete(plan)
    db.flush()
    for position, remaining in enumerate(db.scalars(plans_for_week(db, week.id)), 1):
        remaining.position = position
    payload = main.work_week_json(db, week)
    db.commit()
    return payload
