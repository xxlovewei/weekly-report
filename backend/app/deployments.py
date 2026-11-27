import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from .db import get_db
from .deploy_models import DeploymentItem, DeploymentMemo, DeploymentMemoTarget, DeploymentPlan, DeploymentVersion
from .main import Input, active_session, admin, current_work_week, lock_task_changes, week_row
from .models import BoardTaskDetail, Notification, Task, TaskPlan, Week
from .reviews import NoRedirect, active_projects, get_active_project
from .task_board import add_inbox_card, attach_detail, board_detail, delete_detail, progress_status, put_at_top, update_detail_status

router = APIRouter(prefix="/api/deployments")
SHANGHAI = timezone(timedelta(hours=8))
SITES = {
    "national": "国铁侧", "harbin": "哈尔滨局", "shenyang": "沈阳局", "beijing": "北京局",
    "taiyuan": "太原局", "hohhot": "呼和浩特局", "zhengzhou": "郑州局", "wuhan": "武汉局",
    "xian": "西安局", "jinan": "济南局", "shanghai": "上海局", "nanchang": "南昌局",
    "guangzhou": "广州局", "nanning": "南宁局", "chengdu": "成都局", "kunming": "昆明局",
    "lanzhou": "兰州局", "urumqi": "乌鲁木齐局", "qinghai": "青藏局",
}
NETWORKS = {"internal": "内服网", "external": "外服网", "dedicated": "专网"}
OPEN_STATES = ("draft", "ready")
DEPLOYED_STATES = ("baseline", "succeeded")
HISTORY_STATES = (*DEPLOYED_STATES, "failed")
SHA_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
RefKind = Literal["branches", "tags"]
VersionNumber = Annotated[str, Field(max_length=40, pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")]


class VersionRefsInput(Input):
    branch: str | None = Field(default=None, min_length=1, max_length=1000)
    sha: str | None = Field(default=None, pattern=SHA_PATTERN)
    tag: str | None = Field(default=None, min_length=1, max_length=1000)
    tag_sha: str | None = Field(default=None, pattern=SHA_PATTERN)


class VersionInput(VersionRefsInput):
    number: VersionNumber


class CommitVersionInput(VersionRefsInput):
    number: VersionNumber | None = None


class TargetsInput(Input):
    project_id: int
    version_id: int
    sites: list[str] = Field(min_length=1, max_length=18)


class PlansInput(TargetsInput):
    scheduled_at: AwareDatetime
    upgrade_content: str = ""


class CommitMessagesInput(Input):
    version_id: int | None = None
    version: CommitVersionInput | None = None
    allow_recent: bool = False


class BaselineInput(TargetsInput):
    deployed_at: AwareDatetime | None = None


class MemoInput(Input):
    project_id: int
    title: str = Field(min_length=1, max_length=180)
    notes: str = Field(default="", max_length=5000)
    sites: list[str] | None = Field(default=None, min_length=1, max_length=18)


class RevisionInput(Input):
    revision: int = Field(ge=0)


class ScheduleInput(RevisionInput):
    scheduled_at: AwareDatetime
    upgrade_content: str | None = None
    version: VersionInput | None = None


class ChecklistInput(RevisionInput):
    removed_ids: list[int]


class CompletionInput(Input):
    done: bool


class SuccessInput(RevisionInput):
    deployed_at: AwareDatetime | None = None


class ResultInput(RevisionInput):
    result: Literal["succeeded", "failed"]
    actual_at: AwareDatetime


def available_sites(project):
    if project.deployment_network not in NETWORKS:
        return []
    if project.deployment_level == "national":
        return ["national"]
    if project.deployment_level == "regional":
        return list(SITES)[1:]
    return []


def checked_sites(project, sites):
    allowed = available_sites(project)
    if not allowed:
        raise HTTPException(422, "请先在审查配置设置项目的部署级别和网络")
    chosen = allowed if sites is None else sites
    if len(chosen) != len(set(chosen)) or not set(chosen).issubset(allowed):
        raise HTTPException(422, "请选择该项目的有效部署机房")
    return chosen


def gitlab_repository(project):
    base = project.gitlab_url
    if not base or not project.gitlab_id:
        raise HTTPException(422, "请在审查配置补齐项目的 GitLab 地址和项目 ID")
    allowed = {value.strip().rstrip("/") for value in os.getenv("REVIEW_GITLAB_URLS", "").split(",")}
    try:
        tokens = json.loads(os.getenv("DEPLOYMENT_GITLAB_TOKENS") or "{}")
        token = tokens.get(base) if isinstance(tokens, dict) and base in allowed else None
    except ValueError:
        token = None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(503, "管理员尚未配置此 GitLab 实例的发版只读凭据")
    return f"{base}/api/v4/projects/{project.gitlab_id}/repository", token


def read_gitlab_json(url, token):
    with build_opener(NoRedirect()).open(Request(url, headers={"PRIVATE-TOKEN": token}), timeout=10) as response:
        return json.load(response), response.headers.get("X-Next-Page")


def gitlab_refs(project, kind: RefKind, *, name=None, search="", page=1):
    label = "分支" if kind == "branches" else "标签"
    repository, token = gitlab_repository(project)
    size = 25
    path = f"/{kind}"
    if name is not None:
        if name in {".", ".."}:
            raise HTTPException(422, f"请选择当前项目的 GitLab {label}")
        path += "/" + quote(name, safe="")
    else:
        path += "?" + urlencode({"search": search, "page": page, "per_page": size})
    try:
        data, next_page = read_gitlab_json(repository + path, token)
        if name is not None:
            if data["name"] != name:
                raise ValueError("unexpected GitLab ref")
            return ref_json(project, kind, data)
        items = [ref_json(project, kind, item) for item in data]
        return {"items": items, "has_more": bool(next_page) if next_page is not None else len(items) == size}
    except HTTPError as error:
        if error.code == 404 and name is not None:
            raise HTTPException(422, f"GitLab {label}不存在或当前凭据无法访问，请重新选择") from error
        raise HTTPException(502, "GitLab 请求失败，请检查发版凭据和项目访问权限") from error
    except (URLError, TimeoutError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(502, f"GitLab {label}请求失败，请稍后重试") from error


def ref_json(project, kind: RefKind, data):
    name = data["name"]
    sha = data["commit"]["id"]
    if not isinstance(name, str) or not 0 < len(name) <= 1000 or not re.fullmatch(SHA_PATTERN, sha):
        raise ValueError("invalid GitLab ref")
    directory = "tree" if kind == "branches" else "tags"
    return {"name": name, "url": f"{project.url}/-/{directory}/{quote(name, safe='')}", "sha": sha}


def version_key(number):
    return tuple(int(part) for part in number.split("."))


def version_json(version):
    if version is None:
        return None
    return {"id": version.id, "number": version.number, "branch": version.branch,
            "branch_url": version.branch_url, "sha": version.sha, "tag": version.tag,
            "tag_url": version.tag_url, "tag_sha": version.tag_sha}


def versions(db, project_id):
    rows = db.scalars(select(DeploymentVersion).where(DeploymentVersion.project_id == project_id))
    return sorted(rows, key=lambda row: version_key(row.number), reverse=True)


def target_plans(project, site):
    return select(DeploymentPlan).where(DeploymentPlan.project_id == project.id,
                                        DeploymentPlan.network == project.deployment_network, DeploymentPlan.site == site)


def current_plan(db, project, site):
    return db.scalar(target_plans(project, site).where(DeploymentPlan.status.in_(DEPLOYED_STATES))
                     .order_by(DeploymentPlan.id.desc()).limit(1))


def previous_release(db, project_id, number):
    # 按版本号找前一个已上线版本。同一版本有多条记录时使用最近一条的引用快照。
    target = version_key(number) if number else None
    releases = db.scalars(select(DeploymentPlan).where(DeploymentPlan.project_id == project_id,
                         DeploymentPlan.status.in_(DEPLOYED_STATES)).order_by(DeploymentPlan.id.desc()))
    return max((plan for plan in releases if target is None or version_key(plan.version.number) < target),
               key=lambda plan: version_key(plan.version.number), default=None)


def gitlab_commit_messages(project, sha, previous_sha):
    if sha == previous_sha:
        return []
    repository, token = gitlab_repository(project)
    # 用提交哈希固定范围，防止分支移动时分页结果发生偏移。
    size = 100
    params = {"ref_name": f"{previous_sha}..{sha}" if previous_sha else sha, "per_page": size}
    if not previous_sha:
        now = datetime.now(timezone.utc)
        params["since"] = (now - timedelta(weeks=2)).isoformat(timespec="seconds")
        params["until"] = now.isoformat(timespec="seconds")
    messages = []
    page = 1
    try:
        while True:
            query = urlencode({**params, "page": page})
            commits, next_page = read_gitlab_json(f"{repository}/commits?{query}", token)
            if not isinstance(commits, list):
                raise ValueError("invalid GitLab commit list")
            messages.extend(commit["message"].rstrip("\r\n") for commit in commits)
            has_more = bool(next_page) if next_page is not None else len(commits) == size
            if not commits or not has_more:
                return messages
            page += 1
    except (URLError, TimeoutError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise HTTPException(502, "无法获取 GitLab 提交记录，请检查项目访问权限和版本引用后重试") from error


def checklist_complete(plan):
    if plan.status == "draft":
        return not plan.items
    return plan.status == "ready" and all(item.done and item.card_id is not None for item in plan.items if not item.removed)


def plan_version_json(plan):
    return {**version_json(plan.version), **(plan.version_refs or {})}


def plan_json(plan, *, details=False, actor=None):
    result = {key: getattr(plan, key) for key in ("id", "project_id", "project_name", "site", "network", "status",
                                                 "scheduled_at", "upgrade_content", "deployed_at", "rolled_back_at",
                                                 "confirmed_by", "revision")}
    result.update(version=plan_version_json(plan), from_version=version_json(plan.from_version),
                  checklist_count=len(plan.items), can_confirm=checklist_complete(plan))
    if details:
        result["items"] = [item_json(item, actor) for item in plan.items]
    return result


def item_json(item, actor):
    allowed = actor is not None and (actor.has_role("admin") or actor.id == item.memo.author_id)
    source_version = item.source_version
    if item.plan.status in OPEN_STATES:
        source_version = item.memo.version.number if item.memo.version else None
    return {"id": item.id, "title": item.title, "notes": item.notes, "author": item.author_name,
            "source_version": source_version, "removed": item.removed, "done": item.done, "dispatched": item.card_id is not None,
            "can_complete": allowed and item.plan.status == "ready" and not item.removed}


@router.get("/overview")
def overview(_=Depends(active_session), db: Session = Depends(get_db)):
    projects = [{"id": row.id, "name": row.alias, "level": row.deployment_level, "network": row.deployment_network,
                 "sites": available_sites(row)} for row in active_projects(db)]
    active = {project["id"]: project for project in projects}
    rows = db.scalars(select(DeploymentPlan).options(selectinload(DeploymentPlan.items)).where(
        DeploymentPlan.project_id.in_(active), DeploymentPlan.status.in_((*DEPLOYED_STATES, *OPEN_STATES)))
        .order_by(DeploymentPlan.id))
    targets = {}
    for plan in rows:
        project = active[plan.project_id]
        if plan.network != project["network"] or plan.site not in project["sites"]:
            continue
        target = targets.setdefault((plan.project_id, plan.site), {})
        target["current" if plan.status in DEPLOYED_STATES else "planned"] = plan_json(plan)
    history_projects = db.execute(
        select(DeploymentPlan.project_id, DeploymentPlan.project_name)
        .where(DeploymentPlan.status.in_(HISTORY_STATES))
        .distinct(DeploymentPlan.project_id).order_by(DeploymentPlan.project_id, DeploymentPlan.id.desc())
    )
    return {"projects": projects, "sites": SITES, "networks": NETWORKS,
            "history_projects": [{"id": project_id, "name": name} for project_id, name in history_projects],
            "targets": [{"project_id": project_id, "site": site, **data} for (project_id, site), data in targets.items()]}


@router.get("/projects/{project_id}/branches")
def branches(project_id: int, search: str = Query(default="", max_length=1000), page: int = Query(default=1, ge=1),
             _=Depends(admin), db: Session = Depends(get_db)):
    return gitlab_refs(get_active_project(db, project_id), "branches", search=search, page=page)


@router.get("/projects/{project_id}/tags")
def tags(project_id: int, search: str = Query(default="", max_length=1000), page: int = Query(default=1, ge=1),
         _=Depends(admin), db: Session = Depends(get_db)):
    return gitlab_refs(get_active_project(db, project_id), "tags", search=search, page=page)


@router.get("/projects/{project_id}/versions")
def list_versions(project_id: int, _=Depends(admin), db: Session = Depends(get_db)):
    get_active_project(db, project_id)
    return [version_json(row) for row in versions(db, project_id)]


def resolve_version_refs(project, data, current=None):
    values = {}
    for kind, name_key, url_key, sha_key, label in (
        ("branches", "branch", "branch_url", "sha", "分支"), ("tags", "tag", "tag_url", "tag_sha", "标签"),
    ):
        name, sha = getattr(data, name_key), getattr(data, sha_key)
        if name is None and sha is not None:
            raise HTTPException(422, f"请选择提交对应的 GitLab {label}")
        if current is not None and (name, sha) == (current[name_key], current[sha_key]):
            values.update({key: current[key] for key in (name_key, url_key, sha_key)})
            continue
        ref = gitlab_refs(project, kind, name=name) if name is not None else None
        if ref is not None and sha is not None and sha != ref["sha"]:
            raise HTTPException(409, f"{label}提交已更新，请重新查询和选择{label}")
        values.update({name_key: name, url_key: ref["url"] if ref else None, sha_key: ref["sha"] if ref else None})
    return values


@router.post("/projects/{project_id}/commit-messages")
def commit_messages(project_id: int, data: CommitMessagesInput, _=Depends(admin), db: Session = Depends(get_db)):
    project = get_active_project(db, project_id)
    checked_sites(project, None)
    if (data.version_id is None) == (data.version is None):
        raise HTTPException(422, "请选择一个已有版本或填写新版本")
    current = data.version if data.version_id is None else db.get(DeploymentVersion, data.version_id)
    if current is None or (data.version_id is not None and current.project_id != project_id):
        raise HTTPException(422, "请选择该项目的有效版本")
    if not (current.tag or current.branch):
        raise HTTPException(422, "请先选择 GitLab 分支或标签")
    previous = previous_release(db, project_id, current.number)
    if previous is None and not data.allow_recent:
        return {"requires_recent_confirmation": True}
    previous_sha = None
    if previous is not None:
        refs = plan_version_json(previous)
        previous_sha = refs["tag_sha"] or refs["sha"]
        if not previous_sha:
            raise HTTPException(422, f"上一发版版本 {previous.version.number} 未记录 GitLab 提交，无法比较提交范围")
    if data.version is not None:
        refs = resolve_version_refs(project, data.version)
        sha = refs["tag_sha"] or refs["sha"]
    else:
        sha = current.tag_sha or current.sha
    if not sha:
        raise HTTPException(422, "所选版本未记录 GitLab 提交，请重新选择分支或标签")
    return {"messages": gitlab_commit_messages(project, sha, previous_sha)}


def save_version(db, project_id, data):
    project = get_active_project(db, project_id)
    checked_sites(project, None)
    mapping = (project.gitlab_url, project.gitlab_id, project.url)
    refs = resolve_version_refs(project, data)
    lock_task_changes(db)
    db.refresh(project)
    if not project.active or mapping != (project.gitlab_url, project.gitlab_id, project.url):
        raise HTTPException(409, "项目配置已变化，请重新选择")
    checked_sites(project, None)
    existing = versions(db, project_id)
    if existing and version_key(data.number) <= version_key(existing[0].number):
        raise HTTPException(409, f"新版本号必须高于已有最高版本 {existing[0].number}")
    row = DeploymentVersion(project_id=project_id, number=data.number, **refs)
    db.add(row)
    db.commit()
    return version_json(row)


@router.post("/projects/{project_id}/versions", status_code=201)
def add_version(project_id: int, data: VersionInput, _=Depends(admin), db: Session = Depends(get_db)):
    return save_version(db, project_id, data)


@router.post("/projects/{project_id}/baseline-versions", status_code=201)
def add_baseline_version(project_id: int, data: VersionInput, _=Depends(admin), db: Session = Depends(get_db)):
    return save_version(db, project_id, data)


def checked_targets(db, data):
    project = get_active_project(db, data.project_id)
    sites = checked_sites(project, data.sites)
    version = db.get(DeploymentVersion, data.version_id)
    if version is None or version.project_id != project.id:
        raise HTTPException(422, "请选择该项目的有效版本")
    return project, sites, version


def new_plan(project, site, version, **fields):
    return DeploymentPlan(project_id=project.id, project_name=project.alias, network=project.deployment_network,
                          site=site, version=version, **fields)


@router.post("/baselines", status_code=201)
def add_baseline(data: BaselineInput, actor=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    project, sites, version = checked_targets(db, data)
    if data.deployed_at and data.deployed_at > datetime.now(timezone.utc):
        raise HTTPException(422, "实际发版时间不能晚于当前时间")
    rows = []
    for site in sites:
        if db.scalar(target_plans(project, site).where(DeploymentPlan.status.in_((*DEPLOYED_STATES, *OPEN_STATES))).limit(1)):
            raise HTTPException(409, f"{SITES[site]}已有历史或发版计划")
        rows.append(new_plan(project, site, version, status="baseline", deployed_at=data.deployed_at,
                             confirmed_by=actor.display_name))
    db.add_all(rows)
    db.commit()
    return [plan_json(row) for row in rows]


def memo_candidates(db, plan):
    # 以成功计划的执行结果为准。尚未执行的归档事项继续随该机房的后续计划滚动。
    history = db.execute(select(DeploymentItem.memo_id, DeploymentItem.done, DeploymentItem.removed).join(DeploymentPlan)
                         .where(DeploymentPlan.project_id == plan.project_id, DeploymentPlan.site == plan.site,
                                DeploymentPlan.network == plan.network, DeploymentPlan.status == "succeeded")).all()
    handled = {memo_id for memo_id, done, removed in history if done and not removed}
    skipped = {memo_id for memo_id, _, removed in history if removed}
    baseline = db.scalar(select(DeploymentVersion.number).select_from(DeploymentPlan)
                         .join(DeploymentVersion, DeploymentPlan.version_id == DeploymentVersion.id)
                         .where(DeploymentPlan.project_id == plan.project_id, DeploymentPlan.site == plan.site,
                                DeploymentPlan.network == plan.network, DeploymentPlan.status == "baseline"))
    earliest = version_key(baseline) if baseline else None
    latest = version_key(plan.version.number)
    rows = db.scalars(select(DeploymentMemo).join(DeploymentMemoTarget)
                      .where(DeploymentMemo.project_id == plan.project_id, DeploymentMemo.network == plan.network,
                             DeploymentMemo.deleted_at.is_(None),
                             DeploymentMemoTarget.site == plan.site, DeploymentMemo.id.not_in(handled))
                      .order_by(DeploymentMemo.id))
    # 已补录的基线覆盖更早的归档事项；基线后明确移除的事项仍需处理。
    return {memo.id: memo for memo in rows if memo.version is None or (
        version_key(memo.version.number) <= latest
        and (earliest is None or version_key(memo.version.number) > earliest or memo.id in skipped)
    )}


def append_candidates(plan, candidates, seen):
    for memo_id, memo in candidates.items():
        if memo_id not in seen:
            plan.items.append(DeploymentItem(memo=memo, title=memo.title, notes=memo.notes,
                                             author_name=memo.author.display_name))


@router.post("/plans", status_code=201)
def create_plans(data: PlansInput, _=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    project, sites, version = checked_targets(db, data)
    rows = []
    for site in sites:
        if db.scalar(target_plans(project, site).where(DeploymentPlan.status.in_(OPEN_STATES)).limit(1)):
            raise HTTPException(409, f"{SITES[site]}已有待执行计划")
        current = current_plan(db, project, site)
        if current and version_key(version.number) <= version_key(current.version.number):
            raise HTTPException(422, f"目标版本必须高于{SITES[site]}当前版本 {current.version.number}")
        row = new_plan(project, site, version, from_version=current.version if current else None,
                       scheduled_at=data.scheduled_at, upgrade_content=data.upgrade_content, status="draft")
        append_candidates(row, memo_candidates(db, row), set())
        rows.append(row)
    db.add_all(rows)
    db.commit()
    return [plan_json(row) for row in rows]


@router.get("/plans")
def list_plans(project_id: int | None = None, site: str | None = None, network: str | None = None,
               version: str | None = None, start: date | None = None, end: date | None = None,
               history: bool = False, include_open: bool | None = None,
               status: Literal["draft", "ready", "baseline", "succeeded", "failed"] | None = None,
               page: int | None = Query(default=None, ge=1), page_size: int = Query(default=20, ge=1, le=100),
               _=Depends(active_session), db: Session = Depends(get_db)):
    with_open = not history if include_open is None else include_open
    states = (OPEN_STATES if with_open else ()) + (HISTORY_STATES if history else ())
    filters = [DeploymentPlan.status.in_(states)]
    is_open = DeploymentPlan.status.in_(OPEN_STATES)
    actual_at = func.coalesce(DeploymentPlan.rolled_back_at, DeploymentPlan.deployed_at)
    # 待执行以计划时间筛选，历史以实际发版或回滚时间筛选。
    list_date = case((is_open, DeploymentPlan.scheduled_at), else_=actual_at)
    for column, value in ((DeploymentPlan.project_id, project_id), (DeploymentPlan.site, site),
                          (DeploymentPlan.network, network), (DeploymentPlan.status, status)):
        if value is not None:
            filters.append(column == value)
    if version:
        filters.append(DeploymentPlan.version.has(DeploymentVersion.number == version.strip()))
    if start:
        filters.append(list_date >= datetime.combine(start, time.min, tzinfo=SHANGHAI))
    if end:
        filters.append(list_date <= datetime.combine(end, time.max, tzinfo=SHANGHAI))
    query = select(DeploymentPlan).options(selectinload(DeploymentPlan.items)).where(*filters).order_by(
        is_open.desc(), case((is_open, list_date)).asc().nulls_last(),
        case((~is_open, list_date)).desc().nulls_last(), DeploymentPlan.id.desc(),
    )
    if page is None:
        return [plan_json(row) for row in db.scalars(query)]
    total = db.scalar(select(func.count()).select_from(DeploymentPlan).where(*filters))
    page = min(page, max(1, (total + page_size - 1) // page_size))
    items = [plan_json(row) for row in db.scalars(query.limit(page_size).offset((page - 1) * page_size))]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_plan(db, plan_id):
    plan = db.get(DeploymentPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "发版计划不存在")
    return plan


@router.get("/plans/{plan_id}")
def plan_details(plan_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    return plan_json(get_plan(db, plan_id), details=True, actor=auth[0])


def editable_plan(db, plan_id, revision):
    lock_task_changes(db)
    plan = get_plan(db, plan_id)
    if plan.status not in OPEN_STATES or plan.revision != revision:
        raise HTTPException(409, "计划状态或内容已变化，请重新载入")
    return plan


def check_current_target(db, plan):
    project = get_active_project(db, plan.project_id)
    if plan.network != project.deployment_network or plan.site not in available_sites(project):
        raise HTTPException(409, "项目部署配置已变化，请取消原计划后重新安排")
    prior = current_plan(db, project, plan.site)
    if (prior.version_id if prior else None) != plan.from_version_id:
        raise HTTPException(409, "机房当前版本已变化，请重新安排计划")
    return prior


def withdraw_item(db, item, *, preserve_completion=False, delete_linked_tasks=False):
    # 移除单个检查项时保留周报明细，删除整个计划时收回所有关联任务。
    if item.card:
        card = item.card
        plans = select(TaskPlan).where(TaskPlan.board_task_id == card.id)
        if not delete_linked_tasks:
            plans = plans.where(TaskPlan.applied.is_(False))
        linked_plans = db.scalars(plans).all()
        affected_weeks = {plan.week_id for plan in linked_plans}
        for plan in linked_plans:
            db.delete(plan)
        for week_id in affected_weeks:
            week = db.get(Week, week_id)
            week.revision += 1
            rows = db.scalars(select(TaskPlan).where(TaskPlan.week_id == week_id, TaskPlan.applied.is_(False))
                              .order_by(TaskPlan.position, TaskPlan.id))
            for position, plan in enumerate(rows, 1):
                plan.position = position
        if delete_linked_tasks:
            details = db.scalars(select(Task).join(BoardTaskDetail, BoardTaskDetail.task_id == Task.id)
                                 .where(BoardTaskDetail.board_task_id == card.id)).all()
            for detail in details:
                if detail.week_id not in affected_weeks:
                    detail.week.revision += 1
                delete_detail(db, detail)
        item.card = None
        db.flush()
        db.delete(card)
    if not preserve_completion:
        item.done = False


@router.patch("/plans/{plan_id}/schedule")
def schedule_plan(plan_id: int, data: ScheduleInput, actor=Depends(admin), db: Session = Depends(get_db)):
    if data.version is not None:
        original = get_plan(db, plan_id)
        ensure_draft_version(original)
        if original.revision != data.revision:
            raise HTTPException(409, "计划内容已变化，请重新载入")
        project = get_active_project(db, original.project_id)
        mapping = (project.gitlab_url, project.gitlab_id, project.url)
        refs = resolve_version_refs(project, data.version, plan_version_json(original))
        # GitLab 查询结束后重新核对计划，避免等待外部接口时占用任务事务锁。
        db.expire_all()
    plan = editable_plan(db, plan_id, data.revision)
    prior = check_current_target(db, plan)
    if data.version is not None:
        ensure_draft_version(plan)
        project = get_active_project(db, plan.project_id)
        if mapping != (project.gitlab_url, project.gitlab_id, project.url):
            raise HTTPException(409, "项目配置已变化，请重新选择")
        edit_draft_version(db, plan, data.version.number, refs, prior)
    plan.scheduled_at = data.scheduled_at
    if data.upgrade_content is not None:
        plan.upgrade_content = data.upgrade_content
    plan.revision += 1
    db.commit()
    return plan_json(plan, details=True, actor=actor)


def ensure_draft_version(plan):
    if plan.status != "draft":
        raise HTTPException(409, "检查清单已派发，只能修改计划时间和升级内容")


def edit_draft_version(db, plan, number, refs, prior):
    if prior and version_key(number) <= version_key(prior.version.number):
        raise HTTPException(422, f"目标版本必须高于当前版本 {prior.version.number}")
    previous = plan.version.number
    version = db.scalar(select(DeploymentVersion).where(DeploymentVersion.project_id == plan.project_id,
                                                         DeploymentVersion.number == number))
    if version is None:
        version = DeploymentVersion(project_id=plan.project_id, number=number, **refs)
        db.add(version)
    plan.version = version
    # 同一版本可能被其他机房或历史计划引用，引用变更只写入当前计划。
    plan.version_refs = refs if any(getattr(version, key) != value for key, value in refs.items()) else None
    if number != previous:
        candidates = memo_candidates(db, plan)
        for item in plan.items[:]:
            if item.memo_id not in candidates:
                plan.items.remove(item)
                db.delete(item)
        append_candidates(plan, candidates, {item.memo_id for item in plan.items})


@router.post("/plans/{plan_id}/checklist/refresh")
def refresh_checklist(plan_id: int, data: RevisionInput, actor=Depends(admin), db: Session = Depends(get_db)):
    plan = editable_plan(db, plan_id, data.revision)
    check_current_target(db, plan)
    candidates = memo_candidates(db, plan)
    for item in plan.items:
        if item.memo_id not in candidates:
            item.removed = True
            withdraw_item(db, item)
    append_candidates(plan, candidates, {item.memo_id for item in plan.items})
    plan.revision += 1
    db.commit()
    return plan_json(plan, details=True, actor=actor)


@router.put("/plans/{plan_id}/checklist")
def confirm_checklist(plan_id: int, data: ChecklistInput, actor=Depends(admin), db: Session = Depends(get_db)):
    lock_task_changes(db)
    plan = get_plan(db, plan_id)
    removed = set(data.removed_ids)
    if plan.status == "ready" and plan.revision != data.revision and removed == {i.id for i in plan.items if i.removed} and all(
        item.removed or item.card_id is not None for item in plan.items
    ):
        return plan_json(plan, details=True, actor=actor)
    plan = editable_plan(db, plan_id, data.revision)
    check_current_target(db, plan)
    candidates = memo_candidates(db, plan)
    if not removed.issubset({item.id for item in plan.items}):
        raise HTTPException(422, "请选择当前计划的检查项")
    if candidates.keys() - {item.memo_id for item in plan.items} or any(
        item.memo_id not in candidates and item.id not in removed for item in plan.items
    ):
        raise HTTPException(409, "备忘范围已变化，请刷新候选清单后确认")
    restored = []
    for item in plan.items:
        item.removed = item.id in removed
        if item.removed:
            withdraw_item(db, item, preserve_completion=item.memo_id in candidates)
        elif item.card is None:
            item.card = add_inbox_card(db, item.memo.author_id, name=card_name(plan, item.title),
                                       category_name="发版检查", priority="高", notes=item.notes, top=True)
            db.add(Notification(user_id=item.memo.author_id, kind="发版检查", board_task_id=item.card.id,
                                title=f"{plan.project_name} {plan.version.number} · {card_name(plan, item.title)}"))
            if item.done:
                item.done = False
                restored.append(item)
    plan.status = "ready"
    # 取消移除时恢复已完成的检查项及对应看板状态。
    for item in restored:
        apply_item_completion(db, item, True)
    plan.revision += 1
    db.commit()
    return plan_json(plan, details=True, actor=actor)


def card_name(plan, title):
    return f"【{SITES[plan.site]}】{title}"


def apply_item_completion(db, item, done):
    if item.plan.status != "ready" or item.removed or not item.card:
        raise HTTPException(409, "请在清单确认后执行保留项")
    card = item.card
    if item.done == done:
        return
    state = "done" if done else "in_progress"
    week = week_row(db, card.user_id, current_work_week(), create=True)
    detail = board_detail(db, card.id, week.id)
    status = "已完成" if done else progress_status(db, card, detail)
    if detail is None:
        position = db.scalar(select(func.max(Task.position)).where(Task.week_id == week.id)) or 0
        attach_detail(db, card, week, position + 1, status)
        week.revision += 1
    else:
        update_detail_status(card, detail, status)
    put_at_top(db, card, state)
    card.revision += 1


@router.patch("/plans/{plan_id}/items/{item_id}")
def complete_item(plan_id: int, item_id: int, data: CompletionInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    plan = get_plan(db, plan_id)
    item = next((row for row in plan.items if row.id == item_id), None)
    actor = auth[0]
    if item is None or (not actor.has_role("admin") and item.memo.author_id != actor.id):
        raise HTTPException(404, "可执行的检查项不存在")
    apply_item_completion(db, item, data.done)
    db.commit()
    return plan_json(plan, details=True, actor=actor)


@router.post("/plans/{plan_id}/success")
def confirm_success(plan_id: int, data: SuccessInput, actor=Depends(admin), db: Session = Depends(get_db)):
    return record_result(db, plan_id, data.revision, "succeeded", data.deployed_at or datetime.now(timezone.utc), actor)


@router.post("/plans/{plan_id}/result")
def confirm_result(plan_id: int, data: ResultInput, actor=Depends(admin), db: Session = Depends(get_db)):
    return record_result(db, plan_id, data.revision, data.result, data.actual_at, actor)


def record_result(db, plan_id, revision, result, actual_at, actor):
    lock_task_changes(db)
    plan = get_plan(db, plan_id)
    if plan.status == result:
        return plan_json(plan, details=True, actor=actor)
    plan = editable_plan(db, plan_id, revision)
    prior = check_current_target(db, plan)
    if actual_at > datetime.now(timezone.utc) or (prior and prior.deployed_at and actual_at < prior.deployed_at):
        raise HTTPException(422, "实际发版或回滚时间应介于上次实际发版和当前时间之间")
    if not checklist_complete(plan):
        raise HTTPException(409, "请先确认清单并完成所有保留项")
    if not plan.items:
        candidates = memo_candidates(db, plan)
        if candidates:
            # 零任务计划准备确认时重新检查，防止填结果期间新建的备忘被跳过。
            append_candidates(plan, candidates, set())
            plan.revision += 1
            db.commit()
            raise HTTPException(409, "此计划新增了备忘检查项，请完成检查后确认发版")
    for item in plan.items:
        memo = item.memo
        if result == "succeeded" and not item.removed:
            if memo.version is None:
                memo.version = plan.version
            elif version_key(memo.version.number) > version_key(plan.version.number):
                raise HTTPException(409, "有备忘已归入更高版本，请刷新清单后确认")
        item.source_version = memo.version.number if memo.version else None
    plan.status = result
    if result == "succeeded":
        plan.deployed_at = actual_at
    else:
        plan.rolled_back_at = actual_at
    plan.confirmed_by = actor.display_name
    plan.revision += 1
    db.commit()
    return plan_json(plan, details=True, actor=actor)


@router.post("/plans/{plan_id}/cancel")
def cancel_plan(plan_id: int, data: RevisionInput, actor=Depends(admin), db: Session = Depends(get_db)):
    plan = editable_plan(db, plan_id, data.revision)
    for item in plan.items:
        withdraw_item(db, item, delete_linked_tasks=True)
    plan.status = "cancelled"
    plan.revision += 1
    db.commit()
    return plan_json(plan, details=True, actor=actor)


def memo_json(db, memo):
    relevant = db.execute(select(DeploymentItem, DeploymentPlan).join(DeploymentPlan)
                          .where(DeploymentItem.memo_id == memo.id, DeploymentPlan.status.in_(("ready", "succeeded")))).all()
    by_site = {plan.site: (item, plan) for item, plan in relevant if not item.removed}
    covered = set()
    if memo.version:
        skipped = {plan.site for item, plan in relevant if item.removed and plan.status == "succeeded"}
        baselines = db.execute(select(DeploymentPlan.site, DeploymentVersion.number).select_from(DeploymentPlan)
                               .join(DeploymentVersion, DeploymentPlan.version_id == DeploymentVersion.id)
                               .where(DeploymentPlan.project_id == memo.project_id, DeploymentPlan.network == memo.network,
                                      DeploymentPlan.status == "baseline"))
        covered = {site for site, number in baselines if site not in skipped and
                   version_key(memo.version.number) <= version_key(number)}
    targets = []
    applicable_sites = {target.site for target in memo.targets}
    for site in SITES:
        if site not in applicable_sites:
            continue
        item, plan = by_site.get(site, (None, None))
        targets.append({"site": site, "done": item.done if item else site in covered, "item_id": item.id if item else None,
                        "plan_id": plan.id if plan else None,
                        "baseline_covered": item is None and site in covered,
                        "can_complete": bool(plan and plan.status == "ready" and item.card_id)})
    return {"id": memo.id, "project_id": memo.project_id, "title": memo.title, "notes": memo.notes, "network": memo.network,
            "version": version_json(memo.version), "done": all(target["done"] for target in targets),
            "created_at": memo.created_at, "targets": targets}


@router.get("/memos")
def list_memos(auth=Depends(active_session), db: Session = Depends(get_db)):
    rows = db.scalars(select(DeploymentMemo).where(DeploymentMemo.author_id == auth[0].id,
                                                 DeploymentMemo.deleted_at.is_(None)).order_by(DeploymentMemo.id.desc()))
    return [memo_json(db, memo) for memo in rows]


def own_memo(db, memo_id, actor):
    memo = db.get(DeploymentMemo, memo_id)
    if memo is None or memo.author_id != actor.id or memo.deleted_at is not None:
        raise HTTPException(404, "个人备忘不存在")
    return memo


@router.post("/memos", status_code=201)
def create_memo(data: MemoInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    project = get_active_project(db, data.project_id)
    sites = checked_sites(project, data.sites)
    memo = DeploymentMemo(project_id=project.id, author_id=auth[0].id, title=data.title,
                          notes=data.notes, network=project.deployment_network,
                          targets=[DeploymentMemoTarget(site=site) for site in sites])
    db.add(memo)
    db.commit()
    return memo_json(db, memo)


@router.put("/memos/{memo_id}")
def edit_memo(memo_id: int, data: MemoInput, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    memo = own_memo(db, memo_id, auth[0])
    if memo.version_id is not None:
        raise HTTPException(409, "备忘已关联发版版本，内容已锁定")
    if data.project_id != memo.project_id:
        raise HTTPException(422, "请为其他项目新增备忘")
    project = get_active_project(db, data.project_id)
    sites = set(checked_sites(project, data.sites))
    if memo.network != project.deployment_network:
        raise HTTPException(409, "项目的部署网络已变化，请在当前网络下新增备忘")
    memo.title, memo.notes = data.title, data.notes
    old_sites = {target.site for target in memo.targets}
    memo.targets[:] = [target for target in memo.targets if target.site in sites]
    memo.targets.extend(DeploymentMemoTarget(site=site) for site in sites - old_sites)
    items = db.scalars(select(DeploymentItem).join(DeploymentPlan).where(
        DeploymentItem.memo_id == memo.id, DeploymentPlan.status.in_(OPEN_STATES)))
    for item in items:
        item.title, item.notes = memo.title, memo.notes
        item.plan.revision += 1
        if item.plan.site not in sites:
            item.removed = True
            withdraw_item(db, item)
        elif item.card:
            card = item.card
            card.name, card.notes = card_name(item.plan, memo.title), memo.notes
            card.revision += 1
            week = week_row(db, card.user_id, current_work_week())
            detail = board_detail(db, card.id, week.id) if week else None
            if detail:
                detail.task_group, detail.notes = card.name, card.notes
                week.revision += 1
    db.commit()
    return memo_json(db, memo)


@router.delete("/memos/{memo_id}", status_code=204)
def delete_memo(memo_id: int, auth=Depends(active_session), db: Session = Depends(get_db)):
    lock_task_changes(db)
    memo = own_memo(db, memo_id, auth[0])
    memo.deleted_at = datetime.now(timezone.utc)
    # 保留已归档清单与周报明细，只撤回待执行计划中的检查项。
    items = db.scalars(select(DeploymentItem).join(DeploymentPlan).where(
        DeploymentItem.memo_id == memo.id, DeploymentPlan.status.in_(OPEN_STATES), DeploymentItem.removed.is_(False),
    )).all()
    for item in items:
        item.removed = True
        withdraw_item(db, item)
        item.plan.revision += 1
    db.commit()
