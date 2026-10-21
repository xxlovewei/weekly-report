import hashlib
import os
import secrets
from urllib.parse import urlsplit
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import delete, select, update, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .credential_crypto import EncryptedCredentials, decrypt_credentials, public_key
from .models import Category, Idempotency, LoginSession, Meeting, MeetingTask, Task, User, Week, meeting_updaters

app = FastAPI(title="周报", docs_url="/api/docs", openapi_url="/api/openapi.json")
hasher = PasswordHash.recommended()
STATUSES = {"已完成", "90%", "80%", "70%", "60%", "50%", "40%", "30%", "20%", "10%", "5%"}
SHARED_TYPES = {"开发相关", "联调联试", "数据处理", "运维相关", "开会", "其他"}
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
SESSION_LIFETIME = timedelta(days=7)
LOCKED_MESSAGE = "账号已锁定，请联系管理员。"

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class LoginInput(Input):
    username: str = Field(min_length=1, max_length=80)
    password: str

class PasswordInput(Input):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)

class UserCreate(Input):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["user", "admin"] = "user"
    status: Literal["正常", "锁定"] = "正常"

class UserUpdate(Input):
    username: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None
    status: Literal["正常", "锁定"] | None = None

class ResetPassword(Input):
    password: str = Field(min_length=6, max_length=128)

class CategoryInput(Input):
    name: str = Field(min_length=1, max_length=100)

class TaskPatch(Input):
    category_name: str | None = Field(default=None, max_length=100)
    task_group: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = None
    work_days: list[int] | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value is not None and value not in STATUSES:
            raise ValueError("完成状态无效")
        return value

    @field_validator("work_days")
    @classmethod
    def valid_days(cls, value):
        if value is not None and (len(value) != len(set(value)) or any(d < 1 or d > 7 for d in value)):
            raise ValueError("工作日期只能选择周一至周日，且不能重复")
        return sorted(value) if value is not None else None

class CopyInput(Input):
    mode: Literal["append", "overwrite"] = "append"

class TaskOrderInput(Input):
    task_ids: list[int]

class MeetingTaskInput(Input):
    name: str = Field(min_length=1, max_length=500)
    status: Literal["已完成", "未完成"] | None = None

class MeetingInput(Input):
    meeting_date: date
    meeting_type: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10000)
    needs_follow_up: bool = False
    tasks: list[MeetingTaskInput] = Field(default_factory=list, max_length=100)

    @field_validator("tasks")
    @classmethod
    def valid_tasks(cls, value, info):
        if info.data.get("needs_follow_up") is False and value:
            raise ValueError("只有选择需要跟踪时才能添加关联任务")
        return value

def user_json(user: User):
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "is_active": user.is_active, "status": user.status, "must_change_password": user.must_change_password}

def task_json(task: Task):
    return {"id": task.id, "position": task.position, "category_name": task.category_name, "task_group": task.task_group, "description": task.description, "status": task.status, "work_days": task.work_days, "notes": task.notes}

def meeting_person_json(user: User):
    return {"id": user.id, "username": user.username, "display_name": user.display_name}

def meeting_json(row: Meeting):
    return {"id": row.id, "meeting_date": row.meeting_date.isoformat(), "meeting_type": row.meeting_type, "content": row.content, "needs_follow_up": row.needs_follow_up, "creator": meeting_person_json(row.creator) if row.creator else None, "updaters": [meeting_person_json(user) for user in row.updaters], "tasks": [{"id": task.id, "position": task.position, "name": task.name, "status": task.status} for task in row.tasks]}

def active_session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("zhoubao_session", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.get(LoginSession, token_hash)
    if not row or row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "请先登录")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "账号已停用")
    if user.status == "锁定":
        raise HTTPException(401, LOCKED_MESSAGE)
    if user.must_change_password and request.url.path not in {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}:
        raise HTTPException(403, "请先修改初始密码")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), row.csrf_token):
            raise HTTPException(403, "页面安全验证已失效，请刷新后重试")
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "请求来源无效")
    return user, row

def admin(auth=Depends(active_session)):
    if auth[0].role != "admin":
        raise HTTPException(403, "仅管理员可操作")
    return auth[0]

def monday(value: str):
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "周日期无效")
    if day.weekday() != 0:
        raise HTTPException(422, "周日期必须为周一")
    return day

def week_row(db: Session, user_id: int, start: date, create=False):
    row = db.scalar(select(Week).where(Week.user_id == user_id, Week.start_date == start))
    if not row and create:
        db.execute(insert(Week).values(user_id=user_id, start_date=start, revision=0).on_conflict_do_nothing(index_elements=["user_id", "start_date"]))
        row = db.scalar(select(Week).where(Week.user_id == user_id, Week.start_date == start))
    return row

def week_json(db: Session, row: Week | None):
    if not row:
        return {"revision": 0, "tasks": []}
    tasks = db.scalars(select(Task).where(Task.week_id == row.id).order_by(Task.position, Task.id)).all()
    return {"revision": row.revision, "tasks": [task_json(t) for t in tasks]}

def bump(db: Session, row: Week, expected: int):
    result = db.execute(update(Week).where(Week.id == row.id, Week.revision == expected).values(revision=Week.revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "本周任务已在其他页面更新，请重新载入后保存")
    row.revision = expected + 1

def idempotent(db: Session, user_id: int, key: str | None, operation: str):
    if not key:
        return None
    previous = db.scalar(select(Idempotency).where(Idempotency.user_id == user_id, Idempotency.key == key))
    if previous:
        if previous.operation != operation:
            raise HTTPException(409, "请求标识已被其他操作使用")
        return previous.response
    return None

def store_idempotent(db: Session, user_id: int, key: str | None, operation: str, payload: dict):
    if key:
        db.add(Idempotency(user_id=user_id, key=key, operation=operation, response=payload))

def finish(db: Session, user_id: int, key: str | None, operation: str, payload: dict):
    store_idempotent(db, user_id, key, operation, payload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = idempotent(db, user_id, key, operation)
        if existing is not None:
            return existing
        raise HTTPException(409, "操作冲突，请刷新后重试")
    return payload

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/auth/public-key")
def credential_public_key(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"key": public_key()}

@app.post("/api/auth/login")
def login(encrypted: EncryptedCredentials, response: Response, db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, "/auth/login", LoginInput)
    # Serialize attempts across workers so concurrent failures cannot lose counts.
    user = db.scalar(select(User).where(User.username == data.username.lower()).with_for_update())
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    if user.status == "锁定":
        raise HTTPException(401, LOCKED_MESSAGE)
    if not user.is_active:
        raise HTTPException(401, "用户名或密码错误")
    now = datetime.now(timezone.utc)
    failures = [stamp for stamp in user.failed_login_times if stamp > (now - timedelta(minutes=5)).timestamp()]
    if not hasher.verify(data.password, user.password_hash):
        user.failed_login_times = failures + [now.timestamp()]
        if len(user.failed_login_times) > 5:
            user.status = "锁定"
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        db.commit()
        raise HTTPException(401, LOCKED_MESSAGE if user.status == "锁定" else "用户名或密码错误")
    user.failed_login_times = failures
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + SESSION_LIFETIME
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id, csrf_token=csrf, expires_at=expiry))
    db.commit()
    response.set_cookie("zhoubao_session", token, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=int(SESSION_LIFETIME.total_seconds()), path=COOKIE_PATH)
    return {"user": user_json(user), "csrf_token": csrf}

@app.get("/api/auth/me")
def me(auth=Depends(active_session)):
    return {"user": user_json(auth[0]), "csrf_token": auth[1].csrf_token}

@app.post("/api/auth/logout")
def logout(response: Response, auth=Depends(active_session), db: Session = Depends(get_db)):
    db.delete(auth[1]); db.commit()
    response.delete_cookie("zhoubao_session", path=COOKIE_PATH)
    return {"ok": True}

@app.post("/api/auth/password")
def change_password(encrypted: EncryptedCredentials, auth=Depends(active_session), db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, "/auth/password", PasswordInput)
    user = auth[0]
    if not hasher.verify(data.old_password, user.password_hash):
        raise HTTPException(400, "当前密码错误")
    if data.new_password == data.old_password:
        raise HTTPException(400, "新密码不能与当前密码相同")
    user.password_hash = hasher.hash(data.new_password)
    user.must_change_password = False
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    return {"ok": True}

@app.get("/api/users")
def list_users(_: User = Depends(admin), db: Session = Depends(get_db)):
    return [user_json(x) for x in db.scalars(select(User).order_by(User.id)).all()]

@app.post("/api/users", status_code=201)
def create_user(encrypted: EncryptedCredentials, _: User = Depends(admin), db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, "/users", UserCreate)
    username = data.username.lower()
    if db.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(409, "用户名已存在")
    user = User(username=username, display_name=data.display_name, role=data.role, status=data.status, password_hash=hasher.hash(data.password), must_change_password=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    db.refresh(user)
    return user_json(user)

def protect_last_admin(db: Session, user: User, new_role: str, new_active: bool, new_status: str = "正常"):
    if user.role == "admin" and user.is_active and user.status == "正常" and (new_role != "admin" or not new_active or new_status == "锁定"):
        active_ids = db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True), User.status == "正常").order_by(User.id).with_for_update()).all()
        if len(active_ids) <= 1:
            raise HTTPException(409, "不能停用、锁定或降级最后一位有效管理员")

@app.patch("/api/users/{user_id}")
def edit_user(user_id: int, data: UserUpdate, _: User = Depends(admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    values = data.model_dump(exclude_unset=True)
    protect_last_admin(db, user, values.get("role", user.role), values.get("is_active", user.is_active), values.get("status", user.status))
    if "username" in values and values["username"] is not None:
        values["username"] = values["username"].lower()
        if db.scalar(select(User.id).where(User.username == values["username"], User.id != user_id)):
            raise HTTPException(409, "用户名已存在")
    old_role = user.role
    old_status = user.status
    for key, value in values.items():
        if value is None:
            raise HTTPException(422, "此字段不能为空")
        setattr(user, key, value)
    if old_status == "锁定" and user.status == "正常":
        user.failed_login_times = []
    if not user.is_active or user.role != old_role or user.status == "锁定":
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    return user_json(user)

@app.delete("/api/users/{user_id}")
def disable_user(user_id: int, current: User = Depends(admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    protect_last_admin(db, user, user.role, False)
    user.is_active = False
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id)); db.commit()
    return user_json(user)

@app.post("/api/users/{user_id}/password")
def reset_password(user_id: int, encrypted: EncryptedCredentials, _: User = Depends(admin), db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, f"/users/{user_id}/password", ResetPassword)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hasher.hash(data.password)
    user.must_change_password = True
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id)); db.commit()
    return {"ok": True}

@app.get("/api/categories")
def categories(auth=Depends(active_session), db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(Category).where(Category.user_id == auth[0].id).order_by(Category.name)).all()]

@app.post("/api/categories", status_code=201)
def add_category(data: CategoryInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    user_id = auth[0].id
    if db.scalar(select(Category.id).where(Category.user_id == user_id, Category.name == data.name)):
        raise HTTPException(409, "任务类型已存在")
    row = Category(user_id=user_id, name=data.name); db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "任务类型已存在")
    db.refresh(row)
    return {"id": row.id, "name": row.name}

def own_category(db: Session, category_id: int, user_id: int):
    row = db.get(Category, category_id)
    if not row or row.user_id != user_id:
        raise HTTPException(404, "任务类型不存在")
    return row

@app.patch("/api/categories/{category_id}")
def edit_category(category_id: int, data: CategoryInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = own_category(db, category_id, auth[0].id)
    if db.scalar(select(Category.id).where(Category.user_id == auth[0].id, Category.name == data.name, Category.id != category_id)):
        raise HTTPException(409, "任务类型已存在")
    row.name = data.name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "任务类型已存在")
    return {"id": row.id, "name": row.name}

@app.delete("/api/categories/{category_id}")
def remove_category(category_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    db.delete(own_category(db, category_id, auth[0].id)); db.commit()
    return {"ok": True}

@app.get("/api/weeks/{week_start}")
def get_week(week_start: str, auth=Depends(active_session), db: Session = Depends(get_db)):
    return week_json(db, week_row(db, auth[0].id, monday(week_start)))

def checked_week(db: Session, user_id: int, week_start: str, expected: int):
    row = week_row(db, user_id, monday(week_start), create=True)
    bump(db, row, expected)
    return row

@app.post("/api/weeks/{week_start}/tasks", status_code=201)
def add_task(week_start: str, revision: int, idempotency_key: str | None = Header(default=None), auth=Depends(active_session), db: Session = Depends(get_db)):
    operation = f"add:{week_start}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    row = checked_week(db, auth[0].id, week_start, revision)
    task = Task(week_id=row.id, position=len(week_json(db, row)["tasks"]) + 1, description="", status=None, work_days=[], notes="")
    db.add(task); db.flush()
    return finish(db, auth[0].id, idempotency_key, operation, week_json(db, row))

def own_task(db: Session, task_id: int, week_id: int):
    task = db.get(Task, task_id)
    if not task or task.week_id != week_id:
        raise HTTPException(404, "任务不存在")
    return task

@app.put("/api/weeks/{week_start}/tasks/order")
def reorder_tasks(week_start: str, revision: int, data: TaskOrderInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0].id, week_start, revision)
    tasks = {task.id: task for task in db.scalars(select(Task).where(Task.week_id == row.id)).all()}
    if len(data.task_ids) != len(tasks) or set(data.task_ids) != set(tasks):
        raise HTTPException(422, "排序必须包含本周全部任务，且不能重复")
    for position, task_id in enumerate(data.task_ids, 1):
        tasks[task_id].position = position
    db.flush(); payload = week_json(db, row); db.commit()
    return payload

@app.patch("/api/weeks/{week_start}/tasks/{task_id}")
def edit_task(week_start: str, task_id: int, revision: int, data: TaskPatch, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0].id, week_start, revision)
    task = own_task(db, task_id, row.id)
    values = data.model_dump(exclude_unset=True)
    if "category_name" in values and values["category_name"] is not None:
        if values["category_name"] not in SHARED_TYPES and not db.scalar(select(Category.id).where(Category.user_id == auth[0].id, Category.name == values["category_name"])):
            raise HTTPException(422, "请选择当前可用的任务类型")
    for key, value in values.items():
        if key in {"description", "notes", "work_days", "task_group"} and value is None:
            raise HTTPException(422, "此字段不能为空")
        setattr(task, key, value)
    db.flush()
    payload = week_json(db, row); db.commit()
    return payload

@app.delete("/api/weeks/{week_start}/tasks/{task_id}")
def remove_task(week_start: str, task_id: int, revision: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0].id, week_start, revision)
    db.delete(own_task(db, task_id, row.id)); db.flush()
    for index, task in enumerate(db.scalars(select(Task).where(Task.week_id == row.id).order_by(Task.position, Task.id)).all(), 1):
        task.position = index
    db.flush(); payload = week_json(db, row); db.commit()
    return payload

@app.post("/api/weeks/{week_start}/tasks/{task_id}/duplicate")
def duplicate_task(week_start: str, task_id: int, revision: int, idempotency_key: str | None = Header(default=None), auth=Depends(active_session), db: Session = Depends(get_db)):
    operation = f"duplicate:{week_start}:{task_id}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    row = checked_week(db, auth[0].id, week_start, revision)
    source = own_task(db, task_id, row.id)
    db.execute(update(Task).where(Task.week_id == row.id, Task.position > source.position).values(position=Task.position + 1))
    db.add(Task(week_id=row.id, position=source.position + 1, category_name=source.category_name, task_group=source.task_group, description=source.description, status=source.status, work_days=list(source.work_days), notes=source.notes))
    db.flush()
    return finish(db, auth[0].id, idempotency_key, operation, week_json(db, row))

@app.post("/api/weeks/{week_start}/carry-over")
def carry_over(week_start: str, revision: int, data: CopyInput, idempotency_key: str | None = Header(default=None), auth=Depends(active_session), db: Session = Depends(get_db)):
    operation = f"carry:{week_start}:{data.mode}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    start = monday(week_start)
    source_week = week_row(db, auth[0].id, start - timedelta(days=7))
    # NULL must count as unfinished in SQL's three-valued logic.
    sources = [] if source_week is None else db.scalars(select(Task).where(Task.week_id == source_week.id, (Task.status != "已完成") | Task.status.is_(None)).order_by(Task.position, Task.id)).all()
    if not sources:
        return {**week_json(db, week_row(db, auth[0].id, start)), "no_source": True}
    row = checked_week(db, auth[0].id, week_start, revision)
    existing = db.scalars(select(Task).where(Task.week_id == row.id).order_by(Task.position)).all()
    if data.mode == "overwrite":
        for task in existing: db.delete(task)
        next_position = 1
    else:
        next_position = len(existing) + 1
    db.flush()
    for source in sources:
        db.add(Task(week_id=row.id, position=next_position, category_name=source.category_name, task_group=source.task_group, description=source.description, status=source.status, work_days=[], notes=source.notes))
        next_position += 1
    db.flush()
    return finish(db, auth[0].id, idempotency_key, operation, week_json(db, row))

@app.get("/api/reports/{week_start}")
def report_tabs(week_start: str, auth=Depends(active_session), db: Session = Depends(get_db)):
    start = monday(week_start)
    active = db.scalars(select(User).where(User.is_active.is_(True), User.role != "admin")).all()
    past_ids = db.scalars(select(Week.user_id).join(Task).where(Week.start_date == start).distinct()).all()
    inactive = db.scalars(select(User).where(User.is_active.is_(False), User.role != "admin", User.id.in_(past_ids))).all() if past_ids else []
    users = sorted(active + inactive, key=lambda u: (u.display_name, u.username))
    counts = {}
    for u in users: counts[u.display_name] = counts.get(u.display_name, 0) + 1
    return [{"id": u.id, "name": f"{u.display_name} ({u.username})" if counts[u.display_name] > 1 else u.display_name, "is_active": u.is_active} for u in users]

@app.get("/api/reports/{week_start}/users/{user_id}")
def report_tasks(week_start: str, user_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    start = monday(week_start)
    user = db.get(User, user_id)
    if not user or user.role == "admin":
        raise HTTPException(404, "用户不存在")
    row = week_row(db, user_id, start)
    return week_json(db, row)

@app.get("/api/calendar/marks")
def calendar_marks(year: int, month: int, scope: Literal["work", "reports"], auth=Depends(active_session), db: Session = Depends(get_db)):
    if year < 1900 or year > 2100 or month < 1 or month > 12:
        raise HTTPException(422, "月份无效")
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    end = start + timedelta(days=42)
    query = select(Week.start_date).join(Task).where(Week.start_date >= start, Week.start_date < end)
    if scope == "work":
        query = query.where(Week.user_id == auth[0].id)
    else:
        query = query.join(User, Week.user_id == User.id).where(User.role != "admin")
    return sorted(day.isoformat() for day in db.scalars(query.distinct()).all())

def save_meeting(db: Session, row: Meeting, data: MeetingInput):
    row.meeting_date = data.meeting_date
    row.meeting_type = data.meeting_type
    row.content = data.content
    row.needs_follow_up = data.needs_follow_up
    row.tasks.clear()
    if data.needs_follow_up:
        row.tasks.extend(MeetingTask(position=i, name=task.name, status=task.status) for i, task in enumerate(data.tasks, 1))
    db.commit()
    db.refresh(row)
    return meeting_json(row)

@app.get("/api/meetings")
def list_meetings(page: int = 1, page_size: int = 10, date_from: date | None = None, date_to: date | None = None, content: str = "", status: Literal["已完成", "未完成", "未选择"] | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    if page < 1 or page_size < 1 or page_size > 50 or (date_from and date_to and date_from > date_to):
        raise HTTPException(422, "页码或日期范围无效")
    query = select(Meeting)
    if date_from: query = query.where(Meeting.meeting_date >= date_from)
    if date_to: query = query.where(Meeting.meeting_date <= date_to)
    if content: query = query.where(Meeting.content.ilike(f"%{content}%"))
    if status:
        matching = select(MeetingTask.meeting_id).where(MeetingTask.status.is_(None) if status == "未选择" else MeetingTask.status == status)
        query = query.where(Meeting.id.in_(matching))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Meeting.meeting_date.desc(), Meeting.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [meeting_json(row) for row in rows], "total": total, "page": page, "page_size": page_size}

@app.post("/api/meetings", status_code=201)
def create_meeting(data: MeetingInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = Meeting(creator_id=auth[0].id)
    db.add(row)
    return save_meeting(db, row, data)

@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = db.get(Meeting, meeting_id)
    if not row: raise HTTPException(404, "会议记录不存在")
    return meeting_json(row)

@app.put("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: int, data: MeetingInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = db.get(Meeting, meeting_id)
    if not row: raise HTTPException(404, "会议记录不存在")
    db.execute(insert(meeting_updaters).values(meeting_id=row.id, user_id=auth[0].id).on_conflict_do_nothing())
    return save_meeting(db, row, data)

@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = db.get(Meeting, meeting_id)
    if not row: raise HTTPException(404, "会议记录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
