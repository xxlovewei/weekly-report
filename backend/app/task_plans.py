from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import main
from .db import get_db
from .models import Task, TaskPlan

router = APIRouter(prefix="/api/weeks/{week_start}/plans")


def plans_for_week(db: Session, week_id: int):
    return select(TaskPlan).where(TaskPlan.week_id == week_id).order_by(TaskPlan.position, TaskPlan.id)


def plan_rows(db: Session, week):
    return [main.task_fields_json(plan) for plan in db.scalars(plans_for_week(db, week.id))] if week else []


def apply_current_plans(db: Session, week):
    if not week or week.start_date != main.current_work_week():
        return
    pending = plans_for_week(db, week.id).where(TaskPlan.applied.is_(False))
    if db.scalar(pending.with_only_columns(TaskPlan.id).limit(1)) is None:
        return
    main.lock_task_changes(db)
    if week.start_date != main.current_work_week():
        return
    plans = list(db.scalars(pending))
    if not plans:
        return
    db.refresh(week)
    position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
    for position, plan in enumerate(plans, position + 1):
        # 周任务使用独立副本，后续提交进展不会改动原始计划。
        fields = main.task_fields_json(plan)
        fields.pop("id")
        fields["position"] = position
        db.add(Task(week_id=week.id, **fields))
        plan.applied = True
    week.revision += 1
    db.flush()


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
    position = db.scalar(select(func.max(TaskPlan.position)).where(TaskPlan.week_id == week.id)) or 0
    db.add(TaskPlan(week_id=week.id, position=position + 1))
    db.flush()
    return main.finish(db, actor.id, idempotency_key, operation, main.work_week_json(db, week))


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
    for field, value in main.task_patch_values(db, week.user_id, data).items():
        setattr(plan, field, value)
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
