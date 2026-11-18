from datetime import date, datetime
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Table, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("roles IN ('{user}', '{admin}', '{admin,user}')", name="ck_users_roles"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{user}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default="正常", server_default="正常")
    failed_login_times: Mapped[list[float]] = mapped_column(JSON, default=list, server_default="[]")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    @hybrid_method
    def has_role(self, role: str) -> bool:
        return role in self.roles

    @has_role.expression
    def has_role(cls, role: str):
        return cls.roles.contains([role])

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        CheckConstraint("interval_minutes BETWEEN 1 AND 1440", name="ck_scheduled_tasks_interval"),
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    interval_minutes: Mapped[int] = mapped_column(Integer)

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))

class Week(Base):
    __tablename__ = "weeks"
    __table_args__ = (UniqueConstraint("user_id", "start_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    tasks: Mapped[list["Task"]] = relationship(back_populates="week", order_by="Task.position", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"), index=True)
    meeting_task_id: Mapped[int | None] = mapped_column(ForeignKey("meeting_tasks.id", name="fk_tasks_meeting_task", ondelete="RESTRICT"), nullable=True, index=True)
    meeting_task: Mapped["MeetingTask | None"] = relationship(back_populates="linked_tasks")
    position: Mapped[int] = mapped_column(Integer)
    category_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_group: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # 保存转交时的姓名，之后账号更名也能保留来源。
    transferred_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    work_days: Mapped[list[int]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    week: Mapped[Week] = relationship(back_populates="tasks")

class Idempotency(Base):
    __tablename__ = "idempotency"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(100))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

meeting_updaters = Table(
    "meeting_updaters", Base.metadata,
    Column("meeting_id", ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)

class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    meeting_date: Mapped[date] = mapped_column(Date, index=True)
    meeting_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_meetings_creator_id"), nullable=True)
    creator: Mapped[User | None] = relationship(lazy="joined")
    updaters: Mapped[list[User]] = relationship(secondary=meeting_updaters, order_by=User.id, lazy="selectin")
    needs_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)
    tasks: Mapped[list["MeetingTask"]] = relationship(back_populates="meeting", order_by="MeetingTask.position", cascade="all, delete-orphan")

class MeetingTask(Base):
    __tablename__ = "meeting_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meeting: Mapped[Meeting] = relationship(back_populates="tasks")

    # 每个被指派人仅关联当前有效的周任务；复制时将关联移动到新行。
    linked_tasks: Mapped[list["Task"]] = relationship(back_populates="meeting_task", order_by="Task.id")


class ReleaseRecord(Base):
    """按版本保留生产发版内容，重复启动不覆盖历史记录。"""
    __tablename__ = "release_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewProject(Base):
    __tablename__ = "review_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    alias: Mapped[str] = mapped_column(String(250))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    visibility: Mapped[str] = mapped_column(String(16))
    owner: Mapped[str] = mapped_column(String(250))
    gitlab_url: Mapped[str | None] = mapped_column(String(1000))
    gitlab_id: Mapped[int | None] = mapped_column(Integer)
    skip_slash_branches: Mapped[bool] = mapped_column(Boolean, default=True)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 停用配置后保留日报引用，重新添加同一项目时复用原 ID。
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ReviewRun(Base):
    __tablename__ = "review_runs"
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    commit_date: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(400))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    projects: Mapped[list] = mapped_column(JSON)


class ReviewIssue(Base):
    __tablename__ = "review_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(ForeignKey("review_runs.report_date"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    author: Mapped[str] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), unique=True)
    task_added: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_key: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    review_date: Mapped[date | None] = mapped_column(Date)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
