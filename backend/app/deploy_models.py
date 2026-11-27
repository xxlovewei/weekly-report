from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from .db import Base
from .models import BoardTask, User


class DeploymentVersion(Base):
    __tablename__ = "deployment_versions"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"))
    number: Mapped[str] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(1000))
    branch_url: Mapped[str | None] = mapped_column(Text)
    sha: Mapped[str | None] = mapped_column(String(64))
    tag: Mapped[str | None] = mapped_column(String(1000))
    tag_url: Mapped[str | None] = mapped_column(Text)
    tag_sha: Mapped[str | None] = mapped_column(String(64))


class DeploymentPlan(Base):
    __tablename__ = "deployment_plans"
    __table_args__ = (
        Index("uq_deployment_open_target", "project_id", "site", "network", unique=True,
              postgresql_where=text("status IN ('draft', 'ready')")),
        Index("ix_deployment_target", "project_id", "site", "network", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"))
    project_name: Mapped[str] = mapped_column(String(250))
    site: Mapped[str] = mapped_column(String(16))
    network: Mapped[str] = mapped_column(String(16))
    from_version_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_versions.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("deployment_versions.id"))
    from_version: Mapped[DeploymentVersion | None] = relationship(foreign_keys=[from_version_id], lazy="joined")
    version: Mapped[DeploymentVersion] = relationship(foreign_keys=[version_id], lazy="joined")
    version_refs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upgrade_content: Mapped[str] = mapped_column(Text, default="", server_default="")
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(default=0)
    items: Mapped[list["DeploymentItem"]] = relationship(back_populates="plan", order_by="DeploymentItem.id")


class DeploymentMemo(Base):
    __tablename__ = "deployment_memos"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("review_projects.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    author: Mapped[User] = relationship(lazy="joined")
    title: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str] = mapped_column(Text)
    network: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_versions.id"))
    version: Mapped[DeploymentVersion | None] = relationship(lazy="joined")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    targets: Mapped[list["DeploymentMemoTarget"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class DeploymentMemoTarget(Base):
    __tablename__ = "deployment_memo_targets"

    memo_id: Mapped[int] = mapped_column(ForeignKey("deployment_memos.id", ondelete="CASCADE"), primary_key=True)
    site: Mapped[str] = mapped_column(String(16), primary_key=True)


class DeploymentItem(Base):
    __tablename__ = "deployment_items"
    __table_args__ = (UniqueConstraint("plan_id", "memo_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("deployment_plans.id"))
    plan: Mapped[DeploymentPlan] = relationship(back_populates="items")
    memo_id: Mapped[int] = mapped_column(ForeignKey("deployment_memos.id"), index=True)
    memo: Mapped[DeploymentMemo] = relationship(lazy="joined")
    title: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(120))
    source_version: Mapped[str | None] = mapped_column(String(40))
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("board_tasks.id", ondelete="SET NULL"), unique=True)
    card: Mapped[BoardTask | None] = relationship(backref=backref("deployment_item", uselist=False))
