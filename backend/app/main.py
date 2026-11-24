import hashlib
import os
import secrets
from urllib.parse import urlsplit
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import delete, select, update, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from .db import get_db
from .models import BoardTask, BoardTaskDetail, Category, Idempotency, LoginSession, Meeting, MeetingTask, Notification, ReviewIssue, ReviewRun, Task, TaskPlan, User, Week, ReleaseRecord, meeting_updaters
from .credential_crypto import EncryptedCredentials, decrypt_credentials, public_key

app = FastAPI(title="周报", docs_url="/api/docs", openapi_url="/api/openapi.json")
hasher = PasswordHash.recommended()
STATUSES = {"已完成", "90%", "80%", "70%", "60%", "50%", "40%", "30%", "20%", "10%", "5%"}
BUG_TASK_TYPE = "改bug"
SHARED_TYPES = {"开发相关", BUG_TASK_TYPE, "联调联试", "数据处理", "运维相关", "开会", "其他"}
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
SESSION_LIFETIME = timedelta(days=7)
LOCKED_MESSAGE = "账号已锁定，请联系管理员。"
UserRole = Literal["user", "admin"]

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
    role: UserRole = "user"
    roles: set[UserRole] = Field(default_factory=lambda: {"user"}, min_length=1)
    status: Literal["正常", "锁定"] = "正常"

class UserUpdate(Input):
    username: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    roles: set[UserRole] | None = Field(default=None, min_length=1)
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
    priority: Literal["高", "中", "低"] | None = None
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

class TaskTransferInput(Input):
    user_id: int

class AssignmentInput(Input):
    user_id: int
    status: str | None = None

    _valid_status = field_validator("status")(TaskPatch.valid_status.__func__)

class MeetingTaskInput(Input):
    id: int | None = None
    assignments: list[AssignmentInput] = Field(default_factory=list, max_length=500)
    name: str = Field(max_length=5000)
    status: str | None = None

    _valid_status = field_validator("status")(TaskPatch.valid_status.__func__)

class MeetingInput(Input):
    revision: int | None = None
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
    # 旧客户端仍可读取单角色，权限判断以完整角色列表为准。
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": "admin" if user.has_role("admin") else "user", "roles": user.roles,
            "is_active": user.is_active, "status": user.status, "must_change_password": user.must_change_password}

def task_fields_json(task: Task | TaskPlan):
    return {"id": task.id, "position": task.position, "category_name": task.category_name, "task_group": task.task_group, "description": task.description, "status": task.status, "priority": task.priority, "work_days": task.work_days, "notes": task.notes}

def task_json(task: Task):
    return {**task_fields_json(task), "meeting_task_id": task.meeting_task_id, "transferred_by": task.transferred_by}

def meeting_person_json(user: User):
    return {"id": user.id, "username": user.username, "display_name": user.display_name}

def meeting_task_json(task: MeetingTask):
    db = object_session(task)
    assignments = []
    for card in task.assignments:
        person = db.get(User, card.user_id)
        assignments.append({"user_id": person.id, "status": card.assignment_status, "person": meeting_person_json(person)})
    return {"id": task.id, "position": task.position, "name": task.name, "status": task.status, "assignments": assignments}


def meeting_json(row: Meeting):
    return {"id": row.id, "revision": row.revision, "meeting_date": row.meeting_date.isoformat(), "meeting_type": row.meeting_type, "content": row.content, "needs_follow_up": row.needs_follow_up, "creator": meeting_person_json(row.creator) if row.creator else None, "updaters": [meeting_person_json(user) for user in row.updaters], "tasks": [meeting_task_json(task) for task in row.tasks]}

def active_session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("zhoubao_session", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.get(LoginSession, token_hash)
    if not row or row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "请先登录")
    user = db.get(User, row.user_id)
    if not user or user.is_deleted:
        raise HTTPException(401, "账号已删除")
    if not user.is_active:
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
    if not auth[0].has_role("admin"):
        raise HTTPException(403, "仅管理员可操作")
    return auth[0]

def user_management_admin(request: Request, db: Session = Depends(get_db)):
    # 先串行化账号管理写入，再检查权限，避免并发降级和锁定绕过保护。
    db.execute(text("SELECT pg_advisory_xact_lock(26070502)"))
    return admin(active_session(request, db))

def monday(value: str):
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "周日期无效")
    if day.weekday() != 0:
        raise HTTPException(422, "周日期必须为周一")
    return day

def current_work_week():
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return today - timedelta(days=today.weekday())

def work_owner(db: Session, actor: User, user_id: int | None):
    if user_id is None or user_id == actor.id:
        return actor.id
    if not actor.has_role("admin"):
        raise HTTPException(403, "仅管理员可代管成员任务")
    member = db.get(User, user_id)
    if member is None or member.is_deleted or not member.has_role("user"):
        raise HTTPException(404, "成员不存在")
    return member.id

def writable_week(actor: User, week_start: str):
    start = monday(week_start)
    current = current_work_week()
    if start > current:
        raise HTTPException(403, "未来周请填写任务计划")
    if not actor.has_role("admin") and start != current:
        raise HTTPException(403, "普通用户只能修改当前周的任务明细")
    return start

def self_work_write(user_id: int | None = None, auth=Depends(active_session)):
    if user_id not in (None, auth[0].id):
        raise HTTPException(403, "代管成员任务仅允许查看、修改和删除")
    return auth

@app.get("/api/work-context")
def work_context(auth=Depends(active_session), db: Session = Depends(get_db)):
    actor = auth[0]
    members = []
    if actor.has_role("admin"):
        users = list(db.scalars(select(User).where(User.has_role("user"), User.is_deleted.is_(False))))
        if all(user.id != actor.id for user in users):
            users.append(actor)
        members = member_tags(users)
    return {"current_week": current_work_week().isoformat(), "members": members}

def week_row(db: Session, user_id: int, start: date, create=False):
    row = db.scalar(select(Week).where(Week.user_id == user_id, Week.start_date == start))
    if not row and create:
        db.execute(insert(Week).values(user_id=user_id, start_date=start, revision=0).on_conflict_do_nothing(index_elements=["user_id", "start_date"]))
        row = db.scalar(select(Week).where(Week.user_id == user_id, Week.start_date == start))
    return row

def week_json(db: Session, row: Week | None):
    if not row:
        return {"revision": 0, "tasks": []}
    assignment_count = (select(func.count()).select_from(BoardTask)
                        .where(BoardTask.meeting_task_id == Task.meeting_task_id).correlate(Task).scalar_subquery())
    current = current_work_week()
    prior_detail = prior_detail_exists(BoardTaskDetail.board_task_id, current)
    tasks = db.execute(select(Task, ReviewIssue.id, Meeting.id, Meeting.meeting_date, MeetingTask.name,
                              BoardTaskDetail.board_task_id, assignment_count, prior_detail)
                       .outerjoin(ReviewIssue, ReviewIssue.task_id == Task.id)
                       .outerjoin(MeetingTask, MeetingTask.id == Task.meeting_task_id)
                       .outerjoin(Meeting, Meeting.id == MeetingTask.meeting_id)
                       .outerjoin(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                       .where(Task.week_id == row.id).order_by(Task.position, Task.id))
    return {"revision": row.revision, "tasks": [
        {**task_json(task), "task_group": task.task_group or meeting_name or "",
         "board_task_id": board_task_id, "review_issue_id": issue_id, "meeting_id": meeting_id,
         "meeting_date": meeting_date.isoformat() if meeting_date else None, "name_locked": count > 1,
         "has_history": row.start_date < current or has_prior}
        for task, issue_id, meeting_id, meeting_date, meeting_name, board_task_id, count, has_prior in tasks
    ]}

def work_week_json(db: Session, row: Week | None):
    payload = week_json(db, row)
    plans = plan_rows(db, row)
    if plans:
        payload["plans"] = plans
    return payload

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
    if not user.is_active or user.is_deleted:
        raise HTTPException(401, "用户名或密码错误")
    if user.status == "锁定":
        raise HTTPException(401, LOCKED_MESSAGE)
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
    return [user_json(x) for x in db.scalars(select(User).where(User.is_deleted.is_(False)).order_by(User.id)).all()]

@app.post("/api/users", status_code=201)
def create_user(encrypted: EncryptedCredentials, _: User = Depends(user_management_admin), db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, "/users", UserCreate)
    if {"role", "roles"} <= data.model_fields_set:
        raise HTTPException(422, "角色字段不能同时提交")
    roles = sorted(data.roles) if "roles" in data.model_fields_set else [data.role]
    username = data.username.lower()
    if db.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(409, "用户名已存在")
    user = User(username=username, display_name=data.display_name, roles=roles, status=data.status, password_hash=hasher.hash(data.password), must_change_password=True)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    db.refresh(user)
    return user_json(user)

def protect_last_admin(db: Session, user: User, new_roles: list[str], new_active: bool, new_status: str):
    was_active_admin = user.has_role("admin") and user.is_active and user.status == "正常"
    stays_active_admin = "admin" in new_roles and new_active and new_status == "正常"
    if was_active_admin and not stays_active_admin:
        active_ids = db.scalars(select(User.id).where(
            User.has_role("admin"), User.is_active.is_(True),
            User.is_deleted.is_(False), User.status == "正常",
        ).order_by(User.id).with_for_update()).all()
        if len(active_ids) <= 1:
            raise HTTPException(409, "不能停用、锁定或降级最后一位有效管理员")

@app.patch("/api/users/{user_id}")
def edit_user(user_id: int, data: UserUpdate, _: User = Depends(user_management_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id, with_for_update=True, populate_existing=True)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    values = data.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, "此字段不能为空")
    if "role" in values:
        if "roles" in values:
            raise HTTPException(422, "角色字段不能同时提交")
        role = values.pop("role")
        # 旧客户端保存资料时重发同一单角色，保留账号已有的其他角色。
        if role != ("admin" if user.has_role("admin") else "user"):
            values["roles"] = {role}
    if "roles" in values:
        values["roles"] = sorted(values["roles"])
    new_roles = values.get("roles", user.roles)
    protect_last_admin(db, user, new_roles, values.get("is_active", user.is_active), values.get("status", user.status))
    if "username" in values:
        values["username"] = values["username"].lower()
        if db.scalar(select(User.id).where(User.username == values["username"], User.id != user_id)):
            raise HTTPException(409, "用户名已存在")
    old_roles = user.roles
    old_status = user.status
    for key, value in values.items():
        setattr(user, key, value)
    if old_status == "锁定" and user.status == "正常":
        user.failed_login_times = []
    if not user.is_active or user.roles != old_roles or user.status == "锁定":
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    return user_json(user)

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, _: User = Depends(user_management_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id, with_for_update=True, populate_existing=True)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    if user.has_role("admin"):
        raise HTTPException(403, "请先移除管理员角色，再删除用户")
    user.is_deleted = True
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id)); db.commit()
    return {"ok": True}

@app.post("/api/users/{user_id}/password")
def reset_password(user_id: int, encrypted: EncryptedCredentials, _: User = Depends(user_management_admin), db: Session = Depends(get_db)):
    data = decrypt_credentials(encrypted, f"/users/{user_id}/password", ResetPassword)
    user = db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hasher.hash(data.password)
    user.must_change_password = True
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id)); db.commit()
    return {"ok": True}

@app.get("/api/categories")
def categories(user_id: int | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner = work_owner(db, auth[0], user_id)
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(Category).where(Category.user_id == owner).order_by(Category.name)).all()]

def validate_task_type(db: Session, owner: int, category_name: str):
    if category_name not in SHARED_TYPES and not db.scalar(select(Category.id).where(Category.user_id == owner, Category.name == category_name)):
        raise HTTPException(422, "请选择当前可用的任务类型")

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
def get_week(week_start: str, user_id: int | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    owner, start = work_owner(db, auth[0], user_id), monday(week_start)
    apply_due_plans(db, owner, start)
    row = week_row(db, owner, start)
    payload = work_week_json(db, row)
    db.commit()
    return payload

def lock_task_changes(db: Session):
    # 指派、复制和跨人同步采用同一事务锁，避免跨周加锁顺序造成死锁。
    db.execute(text("SELECT pg_advisory_xact_lock(26070501)"))

def checked_week(db: Session, actor: User, week_start: str, expected: int, user_id: int | None = None):
    lock_task_changes(db)
    start = writable_week(actor, week_start)
    owner = work_owner(db, actor, user_id)
    apply_due_plans(db, owner, start)
    row = week_row(db, owner, start, create=True)
    bump(db, row, expected)
    return row

def require_current_week(week_start: str):
    if monday(week_start) != current_work_week():
        raise HTTPException(403, "只能在当前周新增或复制任务明细")


def ensure_no_task_history(db: Session, week: Week, card: BoardTask | None, current: date, action: str):
    if week.start_date < current or (card and has_prior_detail(db, card.id, current)):
        raise HTTPException(409, f"任务已有历史周明细，无法{action}")


@app.post("/api/weeks/{week_start}/tasks", status_code=201)
def add_task(week_start: str, revision: int, idempotency_key: str | None = Header(default=None), auth=Depends(self_work_write), db: Session = Depends(get_db)):
    lock_task_changes(db)
    require_current_week(week_start)
    operation = f"add:{week_start}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    row = checked_week(db, auth[0], week_start, revision)
    db.execute(update(Task).where(Task.week_id == row.id).values(position=Task.position + 1))
    create_card_for_detail(db, row, Task(week_id=row.id, position=1, task_group=""))
    return finish(db, auth[0].id, idempotency_key, operation, work_week_json(db, row))

def own_task(db: Session, task_id: int, week_id: int):
    task = db.get(Task, task_id)
    if not task or task.week_id != week_id:
        raise HTTPException(404, "任务不存在")
    return task

def transfer_recipients(sender_id: int):
    return select(User).where(
        User.id != sender_id, User.has_role("user"), User.is_active.is_(True),
        User.is_deleted.is_(False), User.status == "正常",
    )

@app.get("/api/task-transfer-recipients")
def list_transfer_recipients(auth=Depends(active_session), db: Session = Depends(get_db)):
    users = db.scalars(transfer_recipients(auth[0].id).order_by(User.display_name, User.username)).all()
    return [meeting_person_json(user) for user in users]

@app.post("/api/weeks/{week_start}/tasks/{task_id}/transfer")
def transfer_task(week_start: str, task_id: int, revision: int, data: TaskTransferInput, auth=Depends(self_work_write), db: Session = Depends(get_db)):
    sender = auth[0]
    source = checked_week(db, sender, week_start, revision)
    task = own_task(db, task_id, source.id)
    source_card = linked_card(db, task_id)
    ensure_no_task_history(db, source, source_card, current_work_week(), "转交")
    hand_off_task(db, sender, data.user_id, source_card, task)
    payload = work_week_json(db, source)
    db.commit()
    return payload


def hand_off_task(db: Session, sender: User, recipient_id: int, source_card: BoardTask | None, task: Task | None):
    recipient = db.scalar(transfer_recipients(sender.id).where(User.id == recipient_id).with_for_update())
    if recipient is None:
        raise HTTPException(422, "请选择其他可用的普通用户")
    meeting_task = source_card.meeting_task if source_card else task.meeting_task
    if meeting_task:
        if any(card.user_id == recipient.id for card in meeting_task.assignments):
            raise HTTPException(409, "接收人已被指派同一会议任务，请选择其他用户")
        meeting_task.meeting.revision += 1

    name = ((task.task_group if task else source_card.name) or (meeting_task.name if meeting_task else "")
            or (task.description if task else "") or "未命名任务")
    issue = source_card.review_issue if source_card else None
    if issue is None and task:
        issue = db.scalar(select(ReviewIssue).where(ReviewIssue.task_id == task.id))
    # 备注和预估工时随卡片送达，进展和工作日待接收人开始任务后恢复到周报。
    handoff = ({"description": task.description, "work_days": task.work_days, "status": task.status}
               if task else source_card.handoff)
    status = task.status if task else source_card.assignment_status
    card = add_inbox_card(db, recipient.id, name=name[:200],
                          category_name=(task.category_name if task else source_card.category_name) or "",
                          priority=(task.priority if task else source_card.priority) or "低",
                          notes=task.notes if task else source_card.notes,
                          estimated_days=source_card.estimated_days if source_card else None,
                          meeting_task_id=meeting_task.id if meeting_task else None,
                          assignment_status=status if meeting_task else None,
                          transferred_by=sender.display_name, handoff=handoff)
    if issue:
        issue.board_task = card
        issue.task_id = None
    if task:
        delete_detail(db, task)
    if source_card:
        db.delete(source_card)
    db.add(Notification(user_id=recipient.id, kind="转交任务", board_task_id=card.id,
                        title=f"{sender.display_name} 转交了任务：{name}"[:500]))

@app.put("/api/weeks/{week_start}/tasks/order")
def reorder_tasks(week_start: str, revision: int, data: TaskOrderInput, auth=Depends(self_work_write), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0], week_start, revision)
    tasks = {task.id: task for task in db.scalars(select(Task).where(Task.week_id == row.id)).all()}
    if len(data.task_ids) != len(tasks) or set(data.task_ids) != set(tasks):
        raise HTTPException(422, "排序必须包含本周全部任务，且不能重复")
    for position, task_id in enumerate(data.task_ids, 1):
        tasks[task_id].position = position
    db.flush(); payload = work_week_json(db, row); db.commit()
    return payload

@app.patch("/api/weeks/{week_start}/tasks/{task_id}")
def edit_task(week_start: str, task_id: int, revision: int, data: TaskPatch, user_id: int | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0], week_start, revision, user_id)
    task = own_task(db, task_id, row.id)
    values = task_patch_values(db, row.user_id, data)
    current = current_work_week()
    card = linked_card(db, task_id)
    renamed = values.get("task_group", task.task_group) != task.task_group
    if renamed:
        ensure_no_task_history(db, row, card, current, "修改任务名称")
        if task.meeting_task and len(task.meeting_task.assignments) > 1:
            raise HTTPException(409, "多人会议任务的名称请在会议记录中修改")
    for key, value in values.items():
        setattr(task, key, value)
    if renamed and task.meeting_task:
        rename_meeting_task(db, task.meeting_task, task.task_group, skip_week_id=row.id)
    if card and row.start_date == current:
        fields = values.keys() if renamed else values.keys() - {"task_group"}
        sync_card_from_detail(db, card, task, fields)
    if "status" in values:
        issue = db.scalar(select(ReviewIssue).where(ReviewIssue.task_id == task.id))
        if issue:
            issue.status = task.status
    db.flush()
    payload = work_week_json(db, row); db.commit()
    return payload

def task_patch_values(db: Session, owner: int, data: TaskPatch):
    values = data.model_dump(exclude_unset=True)
    if values.get("category_name") is not None:
        validate_task_type(db, owner, values["category_name"])
    if any(field in values and values[field] is None for field in ("description", "notes", "work_days", "task_group")):
        raise HTTPException(422, "此字段不能为空")
    return values

@app.delete("/api/weeks/{week_start}/tasks/{task_id}")
def remove_task(week_start: str, task_id: int, revision: int, user_id: int | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    row = checked_week(db, auth[0], week_start, revision, user_id)
    task = own_task(db, task_id, row.id)
    if task.meeting_task_id:
        raise HTTPException(403, "会议指派任务不可删除，请在会议记录中取消指派")
    card = linked_card(db, task_id)
    ensure_no_task_history(db, row, card, current_work_week(), "删除")
    if card:
        card.revision += 1
    delete_detail(db, task)
    db.flush(); payload = work_week_json(db, row); db.commit()
    return payload

def move_meeting_notification(db: Session, source_id: int, target_id: int):
    # 会议关联迁移到新任务行后，原指派通知也定位到新行。
    db.execute(update(Notification).where(Notification.kind == "会议指派", Notification.task_id == source_id)
               .values(task_id=target_id))


@app.post("/api/weeks/{week_start}/tasks/{task_id}/duplicate")
def duplicate_task(week_start: str, task_id: int, revision: int, idempotency_key: str | None = Header(default=None), auth=Depends(self_work_write), db: Session = Depends(get_db)):
    lock_task_changes(db)
    require_current_week(week_start)
    operation = f"duplicate:{week_start}:{task_id}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    row = checked_week(db, auth[0], week_start, revision)
    source = own_task(db, task_id, row.id)
    db.execute(update(Task).where(Task.week_id == row.id, Task.position > source.position).values(position=Task.position + 1))
    name = source.task_group or (source.meeting_task.name[:200] if source.meeting_task else "")
    copied = Task(week_id=row.id, position=source.position + 1, category_name=source.category_name,
                  task_group=name, description=source.description, status=None if source.status == "忽略" else source.status,
                  priority=source.priority, work_days=list(source.work_days), notes=source.notes)
    create_card_for_detail(db, row, copied)
    return finish(db, auth[0].id, idempotency_key, operation, work_week_json(db, row))

@app.post("/api/weeks/{week_start}/add-in-progress")
def add_in_progress(week_start: str, revision: int, idempotency_key: str | None = Header(default=None),
                    auth=Depends(self_work_write), db: Session = Depends(get_db)):
    lock_task_changes(db)
    start = monday(week_start)
    if start != current_work_week():
        raise HTTPException(403, "只能将进行中的任务添加到当前周")
    owner = auth[0].id
    apply_due_plans(db, owner, start)
    operation = f"board:import:{week_start}"
    old = idempotent(db, owner, idempotency_key, operation)
    if old is not None:
        return old
    week = week_row(db, owner, start)
    cards = cards_missing_from_week(db, owner, week)
    if not cards:
        payload = {**work_week_json(db, week), "no_source": True}
        db.commit()
        return payload
    week = checked_week(db, auth[0], week_start, revision)
    position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
    for position, card in enumerate(cards, position + 1):
        status = progress_status(db, card)
        # 批量续做保留完成百分比，本周工作进展重新填写。
        attach_detail(db, card, week, position, status, description="")
        set_assignment_status(card, status)
        card.revision += 1
    return finish(db, owner, idempotency_key, operation, work_week_json(db, week))

@app.post("/api/weeks/{week_start}/carry-over")
def carry_over(week_start: str, revision: int, data: CopyInput, idempotency_key: str | None = Header(default=None), auth=Depends(self_work_write), db: Session = Depends(get_db)):
    lock_task_changes(db)
    start = writable_week(auth[0], week_start)
    operation = f"carry:{week_start}:{data.mode}"
    old = idempotent(db, auth[0].id, idempotency_key, operation)
    if old is not None: return old
    source_week = week_row(db, auth[0].id, start - timedelta(days=7))
    # NULL must count as unfinished in SQL's three-valued logic.
    sources = [] if source_week is None else db.scalars(select(Task).where(Task.week_id == source_week.id, Task.status.not_in(["已完成", "忽略"]) | Task.status.is_(None)).order_by(Task.position, Task.id)).all()
    eligible = []
    row = week_row(db, auth[0].id, start)
    for source in sources:
        link = db.get(BoardTaskDetail, source.id)
        card = db.get(BoardTask, link.board_task_id) if link else None
        if card:
            eligible_state = card.state == "in_progress" or (card.state == "inbox" and source.status is None)
            if start != current_work_week() or not eligible_state or (row and board_detail(db, card.id, row.id)):
                continue
        eligible.append((source, card))
    if not eligible:
        return {**week_json(db, week_row(db, auth[0].id, start)), "no_source": True}
    row = checked_week(db, auth[0], week_start, revision)
    existing = db.scalars(select(Task).where(Task.week_id == row.id).order_by(Task.position)).all()
    if data.mode == "overwrite":
        if existing:
            ensure_no_task_history(db, row, None, current_work_week(), "覆盖")
        if any(task.meeting_task_id for task in existing):
            raise HTTPException(409, "本周含会议指派任务，不可覆盖，请选择追加")
        if any(db.get(BoardTaskDetail, task.id) for task in existing):
            raise HTTPException(409, "本周含看板关联明细，不可覆盖，请选择追加")
        for task in existing: db.delete(task)
        next_position = 1
    else:
        next_position = len(existing) + 1
    db.flush()
    meeting_copies = []
    for source, card in eligible:
        copied = Task(week_id=row.id, position=next_position, category_name=source.category_name, task_group=source.task_group, description=source.description, status=source.status, priority=source.priority, work_days=[], notes=card.notes if card else source.notes, meeting_task_id=source.meeting_task_id, transferred_by=source.transferred_by)
        db.add(copied)
        db.flush()
        if card:
            if card.state == "in_progress" and not (source.status and source.status.endswith("%")):
                copied.status = "5%"
            db.add(BoardTaskDetail(task_id=copied.id, board_task_id=card.id, week_id=row.id))
            card.revision += 1
        issue = db.scalar(select(ReviewIssue).where(ReviewIssue.task_id == source.id))
        if issue:
            issue.task_id = copied.id
        if source.meeting_task_id and not card:
            source.meeting_task_id = None
            source_week.revision += 1
            meeting_copies.append((source.id, copied))
        next_position += 1
    db.flush()
    for source_id, copied in meeting_copies:
        move_meeting_notification(db, source_id, copied.id)
    return finish(db, auth[0].id, idempotency_key, operation, week_json(db, row))

@app.get("/api/reports/{week_start}")
def report_tabs(week_start: str, auth=Depends(active_session), db: Session = Depends(get_db)):
    start = monday(week_start)
    active = db.scalars(select(User).where(User.is_active.is_(True), User.is_deleted.is_(False), User.has_role("user"))).all()
    past_ids = db.scalars(select(Week.user_id).join(Task).where(Week.start_date == start).distinct()).all()
    inactive = db.scalars(select(User).where((User.is_active.is_(False)) | (User.is_deleted.is_(True)), User.has_role("user"), User.id.in_(past_ids))).all() if past_ids else []
    return member_tags(active + inactive)

def member_tags(members: list[User]):
    users = sorted(members, key=lambda u: (u.display_name, u.username))
    counts = {}
    for u in users: counts[u.display_name] = counts.get(u.display_name, 0) + 1
    return [{"id": u.id, "name": f"{u.display_name} ({u.username})" if counts[u.display_name] > 1 else u.display_name, "is_active": u.is_active and not u.is_deleted, "is_deleted": u.is_deleted} for u in users]

@app.get("/api/reports/{week_start}/users/{user_id}")
def report_tasks(week_start: str, user_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    start = monday(week_start)
    user = db.get(User, user_id)
    if not user or not user.has_role("user"):
        raise HTTPException(404, "用户不存在")
    apply_due_plans(db, user_id, start)
    row = week_row(db, user_id, start)
    payload = week_json(db, row)
    db.commit()
    return payload

@app.get("/api/calendar/marks")
def calendar_marks(year: int, month: int, scope: Literal["work", "reports", "review-records"],
                   include_issue_counts: bool = False, user_id: int | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    if year < 1900 or year > 2100 or month < 1 or month > 12:
        raise HTTPException(422, "月份无效")
    first = date(year, month, 1)
    if scope == "review-records":
        # 日报按生成日期标记，只返回当前月的日期。
        next_month = (first + timedelta(days=32)).replace(day=1)
        days = select(ReviewRun.report_date).where(
            ReviewRun.report_date >= first, ReviewRun.report_date < next_month,
        ).order_by(ReviewRun.report_date)
        if include_issue_counts:
            # 保留零问题的日报，按问题 ID 计数以区分零条和多条记录。
            rows = db.execute(days.add_columns(func.count(ReviewIssue.id)).outerjoin(
                ReviewIssue, ReviewIssue.report_date == ReviewRun.report_date,
            ).group_by(ReviewRun.report_date))
            return [{"date": day.isoformat(), "issue_count": count} for day, count in rows]
        return [day.isoformat() for day in db.scalars(days)]
    start = first - timedelta(days=first.weekday())
    end = start + timedelta(days=42)
    query = select(Week.start_date).join(Task).where(Week.start_date >= start, Week.start_date < end)
    if scope == "work":
        query = (select(Week.start_date).where(Week.start_date >= start, Week.start_date < end,
                 Week.user_id == work_owner(db, auth[0], user_id),
                 select(Task.id).where(Task.week_id == Week.id).exists() |
                 select(TaskPlan.id).where(TaskPlan.week_id == Week.id).exists()))
    else:
        query = query.join(User, Week.user_id == User.id).where(User.has_role("user"))
    return sorted(day.isoformat() for day in db.scalars(query.distinct()).all())

def touch_weeks(db: Session, week_ids: set[int]):
    # 同步变更也更新周修订号，让已打开的旧页面得到冲突提示。
    db.flush()
    for week_id in sorted(week_ids):
        week = db.get(Week, week_id)
        week.revision += 1
        for position, task in enumerate(db.scalars(select(Task).where(Task.week_id == week_id).order_by(Task.position, Task.id)), 1):
            task.position = position


def rename_meeting_task(db: Session, task: MeetingTask, name: str, *, skip_week_id: int | None):
    task.name = name
    task.meeting.revision += 1
    for card in task.assignments:
        if card.name != name:
            card.name = name
            card.revision += 1
    affected = set()
    start = current_work_week()
    for linked in task.linked_tasks:
        if linked.week.start_date == start and linked.week_id != skip_week_id:
            linked.task_group = name
            affected.add(linked.week_id)
    touch_weeks(db, affected)


def remove_assignment(db: Session, card: BoardTask, affected: set[int]):
    rows = db.execute(select(Task, Week.start_date).join(Week, Week.id == Task.week_id)
                      .join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                      .where(BoardTaskDetail.board_task_id == card.id))
    start = current_work_week()
    for detail, week_start in rows:
        affected.add(detail.week_id)
        if week_start == start:
            db.delete(detail)
        else:
            detail.meeting_task_id = None
    db.delete(card)


@app.get("/api/meeting-assignees")
def meeting_assignees(auth=Depends(active_session), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.has_role("user"), User.is_deleted.is_(False)).order_by(User.display_name, User.id)).all()
    return [meeting_person_json(user) for user in users]


def save_meeting(db: Session, row: Meeting, data: MeetingInput):
    lock_task_changes(db)
    if row.id:
        db.refresh(row)
        if data.revision is not None and data.revision != row.revision:
            raise HTTPException(409, "会议任务已更新，请关闭并重新打开后编辑")
    row.meeting_date = data.meeting_date
    row.meeting_type = data.meeting_type
    row.content = data.content
    row.needs_follow_up = data.needs_follow_up
    row.revision = (row.revision or 0) + 1
    existing = {task.id: task for task in row.tasks}
    seen = set()
    affected = set()
    new_assignments = []
    start = current_work_week()
    for position, item in enumerate(data.tasks, 1):
        if item.id is not None and (item.id not in existing or item.id in seen):
            raise HTTPException(422, "关联任务无效或重复")
        seen.add(item.id)
        task = existing.get(item.id)
        renamed = task is None or task.name != item.name
        if renamed and len(item.name) > 200:
            raise HTTPException(422, "任务名称最多 200 字")
        if task is None:
            task = MeetingTask(meeting=row)
            db.add(task)
        task.position, task.name, task.status = position, item.name, item.status
        db.flush()
        existing_cards = {card.user_id: card for card in task.assignments}
        selected = set()
        for assignment in item.assignments:
            if assignment.user_id in selected:
                raise HTTPException(422, "指派人员不能重复")
            selected.add(assignment.user_id)
            card = existing_cards.get(assignment.user_id)
            if card is None:
                user = db.get(User, assignment.user_id)
                if not user or not user.has_role("user") or user.is_deleted:
                    raise HTTPException(422, "只能指派普通用户")
                card = add_inbox_card(db, user.id, name=item.name[:200], meeting_task_id=task.id,
                                      assignment_status=assignment.status)
                new_assignments.append(card)
                continue
            status_changed = card.assignment_status != assignment.status
            if renamed:
                card.name = item.name
            card.assignment_status = assignment.status
            week = week_row(db, card.user_id, start)
            detail = board_detail(db, card.id, week.id) if week else None
            if detail:
                if renamed:
                    detail.task_group = item.name
                if status_changed:
                    detail.status = assignment.status
                affected.add(week.id)
            if status_changed and (detail or card.state != "inbox"):
                state = "done" if assignment.status == "已完成" else "in_progress" if assignment.status else "inbox"
                put_at_top(db, card, state)
            card.revision += 1
        for user_id, card in existing_cards.items():
            if user_id not in selected:
                remove_assignment(db, card, affected)
    for task_id, task in existing.items():
        if task_id not in seen:
            remove_meeting_task(db, task, affected)
    touch_weeks(db, affected)
    # 任务箱卡片与通知同时提交，修改已有指派时不会重复发消息。
    db.add_all(Notification(user_id=card.user_id, kind="会议指派", board_task_id=card.id,
                            title=f"{row.meeting_date}会议指派：{card.name or '未命名任务'}"[:500])
               for card in new_assignments)
    db.commit()
    db.expire_all()
    return meeting_json(row)

@app.get("/api/meetings")
def list_meetings(page: int = 1, page_size: int = 10, date_from: date | None = None, date_to: date | None = None, content: str = "", status: str | None = None, auth=Depends(active_session), db: Session = Depends(get_db)):
    if page < 1 or page_size < 1 or page_size > 50 or (date_from and date_to and date_from > date_to):
        raise HTTPException(422, "页码或日期范围无效")
    query = select(Meeting)
    if date_from: query = query.where(Meeting.meeting_date >= date_from)
    if date_to: query = query.where(Meeting.meeting_date <= date_to)
    if content: query = query.where(Meeting.content.ilike(f"%{content}%"))
    if status:
        if status not in STATUSES | {"未开始", "未选择"}:
            raise HTTPException(422, "完成状态无效")
        empty = status in {"未开始", "未选择"}
        # 已指派任务按每人的状态筛选；未指派任务使用自身状态。
        matching = select(MeetingTask.meeting_id).where(
            (~MeetingTask.assignments.any() & (MeetingTask.status.is_(None) if empty else MeetingTask.status == status)) |
            MeetingTask.assignments.any(BoardTask.assignment_status.is_(None) if empty else BoardTask.assignment_status == status))
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
    lock_task_changes(db)
    row = db.get(Meeting, meeting_id)
    if not row: raise HTTPException(404, "会议记录不存在")
    db.execute(insert(meeting_updaters).values(meeting_id=row.id, user_id=auth[0].id).on_conflict_do_nothing())
    return save_meeting(db, row, data)

@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    row = db.get(Meeting, meeting_id)
    if not row: raise HTTPException(404, "会议记录不存在")
    affected = set()
    for task in list(row.tasks):
        remove_meeting_task(db, task, affected)
    touch_weeks(db, affected)
    db.expire(row, ["tasks"])
    db.delete(row)
    db.commit()
    return {"ok": True}


def remove_meeting_task(db: Session, task: MeetingTask, affected: set[int]):
    for card in list(task.assignments):
        remove_assignment(db, card, affected)
    db.flush()
    # 转交后留在原周的历史行仍保留内容，会议被移除时解除链接。
    db.execute(update(Task).where(Task.meeting_task_id == task.id).values(meeting_task_id=None))
    db.expire(task, ["linked_tasks", "assignments"])
    db.delete(task)


@app.get("/api/releases")
def release_notes_history(auth=Depends(active_session), db: Session = Depends(get_db)):
    # 一次读取版本和说明，弹框切换历史版本时无需再次请求。
    rows = db.execute(select(ReleaseRecord.version, ReleaseRecord.description))
    return [{"version": version, "description": description} for version, description in rows]


@app.get("/api/releases/{version}")
def release_notes(version: str, auth=Depends(active_session), db: Session = Depends(get_db)):
    record = db.scalar(select(ReleaseRecord).where(ReleaseRecord.version == version))
    if record is None:
        return None
    return {"version": record.version, "description": record.description, "created_at": record.created_at.isoformat()}


# 子模块复用上面的会话权限和任务事务，定义完成后挂载。
from .notifications import router as notifications_router
from .reviews import router as reviews_router
from .scheduled_tasks import router as scheduled_tasks_router
from .task_board import (add_inbox_card, attach_detail, board_detail, cards_missing_from_week, create_card_for_detail,
                         delete_detail, has_prior_detail, linked_card, prior_detail_exists, progress_status,
                         put_at_top, router as task_board_router, set_assignment_status, sync_card_from_detail)
from .task_plans import apply_due_plans, plan_rows, router as task_plans_router

app.include_router(notifications_router)
app.include_router(reviews_router)
app.include_router(scheduled_tasks_router)
app.include_router(task_board_router)
app.include_router(task_plans_router)
