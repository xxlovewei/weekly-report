import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .credential_crypto import EncryptedCredentials, decrypt_credentials
from .db import get_db
from .main import Input, STATUSES, active_session, admin, lock_task_changes, week_row
from .models import Notification, ReviewIssue, ReviewProject, ReviewRun, Task, User, Week

router = APIRouter(prefix="/api/reviews")
SHANGHAI = timezone(timedelta(hours=8))
SEVERITIES = ("严重", "高危", "中危", "低危", "提示")


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=250)
    alias: str = Field(default="", max_length=250)
    url: str = Field(min_length=1, max_length=1000)
    visibility: Literal["private", "internal", "public"] = "private"
    owner: str = Field(default="", max_length=250)
    gitlab_url: str | None = Field(default=None, max_length=1000)
    gitlab_id: int | None = Field(default=None, gt=0)
    skip_slash_branches: bool = True

    @field_validator("url", "gitlab_url")
    @classmethod
    def validate_url(cls, value):
        if value is None:
            return None
        try:
            url = urlsplit(value)
            valid = url.scheme in {"https", "http"} and url.hostname and url.port != 0
        except ValueError:
            valid = False
        if not valid or url.username is not None or url.query or url.fragment or any(c.isspace() for c in value) or "\\" in value:
            raise ValueError("请输入不含登录信息的 HTTP 或 HTTPS 地址")
        return value.rstrip("/")


class ProjectSelection(Input):
    # 对本次刷新的 GitLab 项目集执行增减，保留其他实例及手动录入的项目。
    removed_ids: list[int] = Field(default_factory=list, max_length=10000)
    projects: list[ProjectInput] = Field(default_factory=list, max_length=10000)


class ProjectCommon(Input):
    is_common: bool


class GitLabConnection(Input):
    model_config = ConfigDict(str_strip_whitespace=False)
    url: str = Field(max_length=1000)
    username: str = Field(default="", max_length=250)
    password: str = Field(default="", max_length=1024)
    token: str = Field(default="", max_length=1024)
    page: int = Field(default=1, ge=1)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@router.post("/gitlab/projects")
def gitlab_projects(encrypted: EncryptedCredentials, _=Depends(admin)):
    data = decrypt_credentials(encrypted, "/reviews/gitlab/projects", GitLabConnection)
    base = data.url.rstrip("/")
    allowed = os.environ.get("REVIEW_GITLAB_URLS", "").split(",")
    if base not in {value.strip().rstrip("/") for value in allowed if value.strip()}:
        raise HTTPException(422, "此地址未配置 GitLab 中转，请使用支持跨域访问的 HTTPS 地址")
    opener = build_opener(NoRedirect())
    try:
        headers = {"PRIVATE-TOKEN": data.token}
        if not data.token:
            form = urlencode({"grant_type": "password", "username": data.username, "password": data.password, "scope": "read_api"})
            with opener.open(Request(f"{base}/oauth/token", data=form.encode()), timeout=15) as response:
                headers = {"Authorization": "Bearer " + json.load(response)["access_token"]}
        params = urlencode({"per_page": 100, "page": data.page, "order_by": "id", "sort": "asc"})
        with opener.open(Request(f"{base}/api/v4/projects?{params}", headers=headers), timeout=15) as response:
            projects = json.load(response)
    except (URLError, TimeoutError, ValueError, KeyError) as error:
        raise HTTPException(502, "GitLab 请求失败，请检查地址、登录信息与访问权限") from error
    # 浏览器只接收项目字段。中转不落盘、不返回任何登录凭据。
    return [{key: project.get(key) for key in ("id", "name", "web_url", "visibility", "namespace", "owner", "path_with_namespace")}
            for project in projects]


def project_json(row):
    fields = ("id", "name", "alias", "url", "visibility", "owner", "gitlab_url", "gitlab_id", "skip_slash_branches", "is_common")
    return {field: getattr(row, field) for field in fields}


def get_active_project(db, project_id):
    row = db.get(ReviewProject, project_id)
    if not row or not row.active:
        raise HTTPException(404, "审查项目不存在")
    return row


def save_project(db, data, project_id=None):
    current = get_active_project(db, project_id) if project_id is not None else None
    matching = db.scalar(select(ReviewProject).where(ReviewProject.url == data.url))
    if current and matching and current.id != matching.id:
        raise HTTPException(409, "此项目地址已存在")
    if not current and data.gitlab_id and data.gitlab_url:
        current = db.scalar(select(ReviewProject).where(
            ReviewProject.gitlab_id == data.gitlab_id, ReviewProject.gitlab_url == data.gitlab_url,
        ).order_by(ReviewProject.active.desc(), ReviewProject.id).limit(1))
        if current and matching and current.id != matching.id:
            raise HTTPException(409, "此项目地址已存在")
    row = current or matching
    if project_id is None and row and row.active:
        return row
    row = row or ReviewProject()
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    row.alias = data.alias or data.name
    row.active = True
    db.add(row)
    db.flush()
    return row


def worker_auth(authorization: str = Header(default="")):
    token = os.environ.get("REVIEW_WORKER_TOKEN", "")
    if not token:
        raise HTTPException(503, "代码审查任务接口未配置")
    if not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "代码审查任务认证失败")


def active_projects(db):
    return db.scalars(select(ReviewProject).where(ReviewProject.active.is_(True)).order_by(ReviewProject.alias, ReviewProject.id))


@router.get("/projects")
def list_projects(_=Depends(admin), db: Session = Depends(get_db)):
    return [project_json(row) for row in active_projects(db)]


@router.put("/projects")
def select_projects(data: ProjectSelection, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    if data.removed_ids:
        for row in db.scalars(select(ReviewProject).where(ReviewProject.id.in_(data.removed_ids))):
            row.active = False
    for project in data.projects:
        save_project(db, project)
    db.commit()
    return [project_json(row) for row in active_projects(db)]


@router.post("/projects", status_code=201)
def add_project(data: ProjectInput, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    row = save_project(db, data)
    db.commit()
    return project_json(row)


@router.put("/projects/{project_id}")
def edit_project(project_id: int, data: ProjectInput, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    row = save_project(db, data, project_id)
    db.commit()
    return project_json(row)


@router.patch("/projects/{project_id}")
def set_project_common(project_id: int, data: ProjectCommon, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    row = get_active_project(db, project_id)
    # 单独保存常用状态，编辑项目资料时保留该状态。
    row.is_common = data.is_common
    db.commit()
    return project_json(row)


@router.delete("/projects/{project_id}")
def remove_project(project_id: int, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    row = get_active_project(db, project_id)
    row.active = False
    db.commit()
    return {"ok": True}


@router.get("/worker/projects", dependencies=[Depends(worker_auth)])
def worker_projects(db: Session = Depends(get_db)):
    return {"projects": [project_json(row) for row in active_projects(db)],
            "usernames": list(db.scalars(select(User.username)))}


class Finding(Input):
    model_config = ConfigDict(str_strip_whitespace=False)
    project_id: int
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    author: str = Field(max_length=250)
    title: str = Field(min_length=1, max_length=5000)
    severity: Literal["严重", "高危", "中危", "低危", "提示"]
    category: str = Field(default="", max_length=250)
    dimension: str = Field(default="", max_length=250)
    sha: str = Field(max_length=64)
    commit_message: str = Field(max_length=10000)
    path: str = Field(default="", max_length=4000)
    start_line: int | None = None
    end_line: int | None = None
    existing_code: str = Field(default="", max_length=30000)
    risk: str = Field(max_length=30000)
    suggestion: str = Field(default="", max_length=30000)
    suggestion_code: str = Field(default="", max_length=30000)


class CommitSummary(Input):
    sha: str = Field(max_length=64)
    author: str = Field(max_length=250)
    title: str = Field(max_length=5000)
    branches: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial", "failed", "skipped"]
    reason: str = Field(default="", max_length=2000)
    ocr_elapsed: str = Field(default="", max_length=80)
    ocr_comments: int | None = Field(default=None, ge=0)
    ocr_items_failed: int | None = Field(default=None, ge=0)
    ocr_items_selected: int | None = Field(default=None, ge=0)


class ProjectSummary(Input):
    project_id: int
    alias: str = Field(max_length=250)
    commits: list[CommitSummary]
    positives: list[str]
    error: str = Field(default="", max_length=2000)


class DailyReport(Input):
    report_date: date
    commit_date: date
    model: str = Field(min_length=1, max_length=400)
    duration_seconds: int = Field(ge=0)
    projects: list[ProjectSummary]
    issues: list[Finding]


@router.post("/worker/reports", dependencies=[Depends(worker_auth)])
def ingest_report(data: DailyReport, db: Session = Depends(get_db)):
    lock_task_changes(db)
    project_ids = {project.project_id for project in data.projects}
    if (len(project_ids) != len(data.projects) or any(issue.project_id not in project_ids for issue in data.issues)
            or any(db.get(ReviewProject, project_id) is None for project_id in project_ids)):
        raise HTTPException(422, "日报中的项目配置无效")
    # 重跑同一天时保留问题编号、状态、备注和已有任务关联。
    run = db.get(ReviewRun, data.report_date)
    if run is not None and run.commit_date != data.commit_date:
        raise HTTPException(409, "同一日报日期不能对应多个提交日期")
    if run is None:
        run = ReviewRun(report_date=data.report_date, commit_date=data.commit_date)
        db.add(run)
    run.model = data.model
    run.duration_seconds = data.duration_seconds
    run.projects = [project.model_dump() for project in data.projects]
    db.flush()
    for issue in data.issues:
        details = issue.model_dump(exclude={"project_id", "fingerprint", "author", "title", "severity"})
        statement = insert(ReviewIssue).values(
            report_date=run.report_date, project_id=issue.project_id, fingerprint=issue.fingerprint,
            author=issue.author, title=issue.title, severity=issue.severity, details=details,
        )
        # 重跑可更新审查正文。严重程度保留，以免改变已有忽略状态的备注要求。
        db.execute(statement.on_conflict_do_update(
            index_elements=["fingerprint"], where=ReviewIssue.report_date == run.report_date,
            set_={"title": statement.excluded.title, "details": statement.excluded.details},
        ))
    authors = {name.lower() for name in db.scalars(select(ReviewIssue.author).where(ReviewIssue.report_date == run.report_date))}
    users = db.scalars(select(User).where(User.is_active.is_(True), User.is_deleted.is_(False))).all()
    known = {user.username.lower() for user in users}
    unmatched = bool(authors - known)
    coverage_gaps = any(p.error or any(c.status != "complete" for c in p.commits) for p in data.projects)
    for user in users:
        if user.username.lower() not in authors and not (user.role == "admin" and (unmatched or coverage_gaps)):
            continue
        db.execute(insert(Notification).values(
            user_id=user.id, kind="代码审查", event_key=f"review:{data.report_date}",
            title=f"{data.commit_date} 的代码审查日报已生成", review_date=data.report_date,
        ).on_conflict_do_nothing(index_elements=["user_id", "event_key"]))
    db.commit()
    return {"ok": True, "report_date": data.report_date}


def issue_json(row, names, user, task_owner=None):
    author = row.author.lower()
    return {
        **row.details, "id": row.id, "project_id": row.project_id, "author": row.author,
        "author_name": names.get(author, row.author or "无名氏"), "mine": author == user.username.lower(),
        "anonymous": author not in names, "title": row.title, "severity": row.severity,
        "status": row.status, "notes": row.notes, "task_added": row.task_added,
        "editable": task_owner is None or task_owner == user.id or user.role == "admin",
    }


@router.get("/days/{report_date}")
def report_day(report_date: date, auth=Depends(active_session), db: Session = Depends(get_db)):
    run = db.get(ReviewRun, report_date)
    configured_projects = list(active_projects(db))
    projects = {p.id: p.alias for p in configured_projects}
    common_project_ids = [p.id for p in configured_projects if p.is_common]
    if not run:
        return {"summary": None, "issues": [], "projects": projects, "common_project_ids": common_project_ids}
    names = {username.lower(): name for username, name in db.execute(select(User.username, User.display_name))}
    rows = db.execute(select(ReviewIssue, Week.user_id).outerjoin(
        Task, Task.id == ReviewIssue.task_id,
    ).outerjoin(Week, Week.id == Task.week_id).where(ReviewIssue.report_date == report_date).order_by(ReviewIssue.id))
    issues = [issue_json(row, names, auth[0], owner) for row, owner in rows]
    historical = {p["project_id"]: p["alias"] for p in run.projects}
    for issue in issues:
        project_id = issue["project_id"]
        if project_id not in historical and project_id not in projects:
            historical[project_id] = db.get(ReviewProject, project_id).alias
    return {
        "summary": {"report_date": run.report_date, "commit_date": run.commit_date, "model": run.model,
                    "duration_seconds": run.duration_seconds, "projects": run.projects},
        "issues": issues, "projects": {**historical, **projects}, "common_project_ids": common_project_ids,
    }


class IssueEdit(Input):
    status: str | None = None
    notes: str = Field(default="", max_length=5000)


def get_issue(db, issue_id):
    row = db.get(ReviewIssue, issue_id)
    if not row:
        raise HTTPException(404, "审查问题不存在")
    return row


@router.get("/issues/{issue_id}")
def review_issue_detail(issue_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    issue = get_issue(db, issue_id)
    names = {username.lower(): name for username, name in db.execute(
        select(User.username, User.display_name).where(func.lower(User.username) == issue.author.lower())
    )}
    project = db.get(ReviewProject, issue.project_id)
    task = db.get(Task, issue.task_id) if issue.task_id else None
    # 与审查记录使用同一份问题数据，读取接口不修改任务或问题。
    return {**issue_json(issue, names, auth[0], task.week.user_id if task else None), "project_alias": project.alias}


@router.patch("/issues/{issue_id}")
def edit_issue(issue_id: int, data: IssueEdit, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    issue = get_issue(db, issue_id)
    task = db.get(Task, issue.task_id) if issue.task_id else None
    if task and task.week.user_id != auth[0].id and auth[0].role != "admin":
        raise HTTPException(403, "此问题已关联其他用户的任务")
    changes = data.model_dump(exclude_unset=True)
    status = changes.get("status", issue.status)
    notes = changes.get("notes", issue.notes)
    if status is not None and status not in STATUSES | {"忽略"}:
        raise HTTPException(422, "完成状态无效")
    if status == "忽略" and issue.severity in SEVERITIES[:2] and not notes:
        raise HTTPException(422, "忽略高危或严重问题时，必须填写备注说明原因")
    # 自动保存备注时不覆盖其他页面已更新的完成状态。
    issue.status, issue.notes = status, notes
    if task and "status" in changes and task.status != status:
        task.status = status
        task.week.revision += 1
    db.commit()
    return {"ok": True, "status": status, "notes": notes}


@router.post("/issues/{issue_id}/task")
def create_issue_task(issue_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    issue = get_issue(db, issue_id)
    if issue.task_added:
        return {"ok": True}
    today = datetime.now(SHANGHAI).date()
    week = week_row(db, auth[0].id, today - timedelta(days=today.weekday()), create=True)
    position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
    task = Task(week_id=week.id, position=position + 1, category_name="开发相关", task_group="修改代码审查问题",
                description=issue.title, status=issue.status, work_days=[], notes="")
    db.add(task)
    db.flush()
    issue.task_id, issue.task_added = task.id, True
    week.revision += 1
    db.commit()
    return {"ok": True}
