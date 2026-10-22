from datetime import date, datetime
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Table, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default="正常", server_default="正常")
    failed_login_times: Mapped[list[float]] = mapped_column(JSON, default=list, server_default="[]")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

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
    position: Mapped[int] = mapped_column(Integer)
    category_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_group: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    name: Mapped[str] = mapped_column(String(500))
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meeting: Mapped[Meeting] = relationship(back_populates="tasks")
