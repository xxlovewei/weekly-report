import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from tests.test_api import clean_db, client
from app import deployments

ROOT = "/api/deployments"


def project_for(operator, level="regional"):
    response = operator.post("/api/reviews/projects", json={
        "name": "业务系统", "url": "https://gitlab.example.com/team/app",
        "deployment_level": level, "deployment_network": "internal",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def version_for(operator, project, number):
    response = operator.post(f"{ROOT}/projects/{project}/baseline-versions", json={"number": number, "branch": "main"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_plan(operator, project, version, *sites):
    response = operator.post(f"{ROOT}/plans", json={
        "project_id": project, "version_id": version, "sites": sites, "scheduled_at": "2026-01-01T08:00:00+08:00",
    })
    assert response.status_code == 201, response.text
    return response.json()


def details(operator, plan):
    response = operator.get(f"{ROOT}/plans/{plan['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def dispatch(operator, plan, removed=()):
    response = operator.put(f"{ROOT}/plans/{plan['id']}/checklist", json={"revision": plan["revision"], "removed_ids": list(removed)})
    assert response.status_code == 200, response.text
    return response.json()


def success(operator, plan):
    return operator.post(f"{ROOT}/plans/{plan['id']}/success", json={"revision": plan["revision"], "deployed_at": None})


@pytest.fixture
def gitlab_main(monkeypatch):
    monkeypatch.setattr(deployments, "gitlab_refs", lambda project, kind, *, name: {
        "name": name, "sha": "a" * 40, "url": f"{project.url}/-/tree/{name}",
    })


def test_optional_refs_and_multiline_upgrade_content(gitlab_main):
    operator = client("admin")
    project = project_for(operator)
    path = f"{ROOT}/projects/{project}/versions"
    response = operator.post(path, json={"number": "1.0.0"})
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["branch"] is None and version["branch_url"] is None and version["tag"] is None
    response = operator.post(path, json={"number": "1.0.1", "tag": "v1.0.1"})
    assert response.status_code == 201 and response.json()["tag"] == "v1.0.1"
    assert operator.post(path, json={"number": "1.0.2", "sha": "a" * 40}).status_code == 422
    content = "更新运行配置\n补充数据库索引"
    scheduled_at = "2026-11-26T14:00:00+08:00"
    response = operator.post(f"{ROOT}/plans", json={
        "project_id": project, "version_id": version["id"], "sites": ["beijing", "shanghai"],
        "scheduled_at": scheduled_at, "upgrade_content": content,
    })
    assert response.status_code == 201, response.text
    beijing, shanghai = response.json()
    assert details(operator, beijing)["upgrade_content"] == content
    assert details(operator, shanghai)["upgrade_content"] == content
    response = operator.patch(f"{ROOT}/plans/{beijing['id']}/schedule", json={
        "revision": beijing["revision"], "scheduled_at": scheduled_at, "upgrade_content": "调整配置\n验证服务",
    })
    assert response.status_code == 200 and response.json()["upgrade_content"] == "调整配置\n验证服务"
    assert details(operator, shanghai)["upgrade_content"] == content


def test_commit_messages_require_recent_confirmation_and_compare_released_versions(monkeypatch):
    calls = []
    base = "https://gitlab.example.com"
    refs = {"main": "a" * 40, "v1.8.0": "b" * 40, "v1.10.0": "c" * 40}
    long_message = "更新项目配置\n\n" + "补充升级步骤" * 900

    def gitlab_response(url, token):
        path = urlsplit(url)
        assert token == "test-only"
        if path.path.endswith("/commits"):
            params = parse_qs(path.query)
            calls.append(params)
            if params["page"] == ["1"]:
                return [{"message": long_message + "\n", "title": "标题", "id": refs["main"]}], "2"
            return [{"message": "修复上线流程\n"}], ""
        name = unquote(path.path.rsplit("/", 1)[-1])
        return {"name": name, "commit": {"id": refs[name]}}, None

    monkeypatch.setenv("REVIEW_GITLAB_URLS", base)
    monkeypatch.setenv("DEPLOYMENT_GITLAB_TOKENS", json.dumps({base: "test-only"}))
    monkeypatch.setattr(deployments, "read_gitlab_json", gitlab_response)
    operator = client("admin")
    project_id = operator.post("/api/reviews/projects", json={
        "name": "提交记录项目", "url": f"{base}/team/app", "gitlab_url": base, "gitlab_id": 42,
        "deployment_level": "regional", "deployment_network": "internal",
    }).json()["id"]
    path = f"{ROOT}/projects/{project_id}"
    endpoint = f"{path}/commit-messages"
    new_version = {"number": "1.10.0", "branch": "main", "tag": "v1.10.0", "tag_sha": refs["v1.10.0"]}
    payload = {"version": new_version}
    expected = {"messages": [long_message, "修复上线流程"]}

    assert client("alice").post(endpoint, json=payload).status_code == 403
    assert operator.post(endpoint, json=payload).json() == {"requires_recent_confirmation": True}
    assert not calls
    assert operator.post(endpoint, json={**payload, "allow_recent": True}).json() == expected
    assert len(calls) == 2
    for index, params in enumerate(calls, 1):
        assert params["page"] == [str(index)] and params["ref_name"] == [refs["v1.10.0"]]
        assert datetime.fromisoformat(params["until"][0]) - datetime.fromisoformat(params["since"][0]) == timedelta(weeks=2)
    calls.clear()

    prior = operator.post(f"{path}/versions", json={"number": "1.8.0", "branch": "main", "tag": "v1.8.0"}).json()
    assert operator.post(f"{ROOT}/baselines", json={
        "project_id": project_id, "version_id": prior["id"], "sites": ["beijing"],
    }).status_code == 201
    draft = operator.post(f"{path}/versions", json={"number": "1.9.0", "branch": "main"}).json()
    create_plan(operator, project_id, draft["id"], "shanghai")
    saved_version = operator.post(f"{path}/versions", json=new_version).json()
    assert operator.post(endpoint, json={"version_id": saved_version["id"]}).json() == expected
    assert len(calls) == 2
    for params in calls:
        assert params["ref_name"] == [f"{refs['v1.8.0']}..{refs['v1.10.0']}"]
        assert "since" not in params

    content = "\n\n".join(expected["messages"])
    saved = operator.post(f"{ROOT}/plans", json={
        "project_id": project_id, "version_id": saved_version["id"], "sites": ["beijing"],
        "scheduled_at": "2026-01-01T08:00:00+08:00", "upgrade_content": content,
    })
    assert saved.status_code == 201, saved.text
    assert saved.json()[0]["upgrade_content"] == content


def test_draft_version_changes_are_local_and_zero_checklist_can_release(gitlab_main):
    operator, alice = client("admin"), client("alice")
    project = project_for(operator)
    version = version_for(operator, project, "1.0.0")
    beijing, shanghai = create_plan(operator, project, version, "beijing", "shanghai")
    assert beijing["checklist_count"] == 0 and beijing["can_confirm"]
    path = f"{ROOT}/plans/{beijing['id']}"
    edit = {"revision": 0, "scheduled_at": "2026-01-03T08:00:00+08:00", "upgrade_content": "更新说明",
            "version": {"number": "1.0.0", "branch": "release", "tag": "v1.0.0"}}
    changed = operator.patch(f"{path}/schedule", json=edit)
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"]["branch"] == "release"
    assert changed.json()["version"]["tag"] == "v1.0.0"
    assert details(operator, shanghai)["version"]["branch"] == "main"
    edit["revision"] = changed.json()["revision"]
    edit["version"]["number"] = "1.0.1"
    plan = operator.patch(f"{path}/schedule", json=edit).json()
    assert plan["version"]["number"] == "1.0.1"

    actual = {"result": "succeeded", "actual_at": "2026-01-02T08:00:00+08:00"}
    assert operator.post(f"{ROOT}/plans/{shanghai['id']}/result", json={**actual, "revision": 0}).status_code == 200
    assert alice.post(f"{ROOT}/memos", json={"project_id": project, "title": "新检查项", "sites": ["beijing"]}).status_code == 201
    assert operator.post(f"{path}/result", json={**actual, "revision": plan["revision"]}).status_code == 409
    draft = details(operator, plan)
    assert draft["checklist_count"] == 1 and not draft["can_confirm"]
    ready = dispatch(operator, draft)
    edit["revision"] = ready["revision"]
    assert operator.patch(f"{path}/schedule", json=edit).status_code == 409
    del edit["version"]
    assert operator.patch(f"{path}/schedule", json=edit).status_code == 200


def test_dispatch_notifies_owner_and_deleting_plan_cleans_linked_tasks(gitlab_main):
    operator, alice, bob = client("admin"), client("alice"), client("bob")
    project = project_for(operator)
    version = version_for(operator, project, "1.0.0")
    assert alice.post(f"{ROOT}/memos", json={"project_id": project, "title": "检查配置", "sites": ["beijing"]}).status_code == 201
    plan, = create_plan(operator, project, version, "beijing")
    ready = dispatch(operator, plan)
    dispatch(operator, plan)
    board = alice.get("/api/board-tasks").json()
    card, = board["tasks"]
    assert (card["priority"], card["category_name"], card["deployment_plan_id"]) == ("高", "发版检查", plan["id"])
    messages, = alice.get("/api/notifications?kind=发版检查").json()["items"]
    assert messages["target"] == {"board_task": card["id"], "deployment_plan": plan["id"]}
    assert bob.get("/api/notifications?kind=发版检查").json()["items"] == []
    path = f"{ROOT}/plans/{plan['id']}"
    updated = alice.patch(f"{path}/items/{ready['items'][0]['id']}", json={"done": True}).json()
    week = f"/api/weeks/{board['current_week']}"
    assert alice.get(week).json()["tasks"][0]["board_task_id"] == card["id"]
    assert operator.post(f"{path}/cancel", json={"revision": updated["revision"]}).status_code == 200
    assert alice.get("/api/board-tasks").json()["tasks"] == []
    assert alice.get(week).json()["tasks"] == []
    assert "target" not in alice.get("/api/notifications?kind=发版检查").json()["items"][0]


def test_release_result_requires_completed_checklist_and_failure_keeps_current_version(gitlab_main):
    operator, alice = client("admin"), client("alice")
    project = project_for(operator)
    baseline, target = [version_for(operator, project, number) for number in ("1.0.0", "1.1.0")]
    assert operator.post(f"{ROOT}/baselines", json={
        "project_id": project, "version_id": baseline, "sites": ["beijing"],
    }).status_code == 201
    assert alice.post(f"{ROOT}/memos", json={
        "project_id": project, "title": "核对发版配置", "sites": ["beijing"],
    }).status_code == 201
    plan, = create_plan(operator, project, target, "beijing")
    assert not plan["can_confirm"]
    plan = dispatch(operator, plan)
    item, = plan["items"]
    path = f"{ROOT}/plans/{plan['id']}"
    result = {"result": "failed", "actual_at": "2026-01-02T08:00:00+08:00"}
    assert operator.post(f"{path}/result", json={**result, "revision": plan["revision"]}).status_code == 409
    plan = alice.patch(f"{path}/items/{item['id']}", json={"done": True}).json()
    assert plan["can_confirm"]
    removed = dispatch(operator, plan, [item["id"]])
    assert removed["items"][0]["removed"] and not removed["items"][0]["dispatched"]
    restored = dispatch(operator, removed)
    assert restored["items"][0]["done"] and restored["items"][0]["dispatched"]
    card, = alice.get("/api/board-tasks").json()["tasks"]
    assert card["state"] == "done"
    response = operator.post(f"{path}/result", json={**result, "revision": restored["revision"]})
    assert response.status_code == 200, response.text
    failed = response.json()
    assert failed["status"] == "failed" and failed["rolled_back_at"] and failed["deployed_at"] is None
    current, = alice.get(f"{ROOT}/overview").json()["targets"]
    assert current["current"]["version"]["id"] == baseline and "planned" not in current
    assert alice.get(f"{ROOT}/memos").json()[0]["version"] is None
    history, = operator.get(f"{ROOT}/plans?history=true&start=2026-01-02&end=2026-01-02").json()
    assert history["id"] == failed["id"]
    assert operator.post(f"{path}/cancel", json={"revision": failed["revision"]}).status_code == 409
    retry, = create_plan(operator, project, target, "beijing")
    assert retry["from_version"]["id"] == baseline
    assert operator.post(f"{ROOT}/plans/{retry['id']}/cancel", json={"revision": retry["revision"]}).status_code == 200
    assert operator.get(f"{ROOT}/plans").json() == []


def test_multi_site_release_updates_board_memos_and_history(gitlab_main):
    operator, alice, bob = client("admin"), client("alice"), client("bob")
    project = project_for(operator)
    v1, v2, v3 = [version_for(operator, project, number) for number in ("1.9.9", "1.10.0", "1.11.0")]
    assert operator.post(f"{ROOT}/projects/{project}/baseline-versions", json={"number": "1.10.1", "branch": "main"}).status_code == 409
    response = operator.post(f"{ROOT}/baselines", json={"project_id": project, "version_id": v1, "sites": ["beijing", "shanghai", "wuhan"]})
    assert response.status_code == 201, response.text
    response = operator.post(f"{ROOT}/baselines", json={"project_id": project, "version_id": v2, "sites": ["guangzhou"]})
    assert response.status_code == 201, response.text
    body = {"project_id": project, "title": "执行 SQL", "notes": "脚本说明", "sites": ["beijing", "shanghai", "wuhan", "guangzhou"]}
    memo = alice.post(f"{ROOT}/memos", json=body)
    assert memo.status_code == 201, memo.text
    memo_id = memo.json()["id"]
    other = alice.post(f"{ROOT}/memos", json={**body, "title": "仅上海配置", "sites": ["shanghai"]})
    assert other.status_code == 201, other.text
    assert bob.get(f"{ROOT}/memos").json() == []
    assert alice.get("/api/board-tasks").json()["tasks"] == []
    beijing, shanghai = create_plan(operator, project, v2, "beijing", "shanghai")
    beijing, shanghai = details(operator, beijing), details(operator, shanghai)
    assert [item["title"] for item in beijing["items"]] == ["执行 SQL"]
    assert len(shanghai["items"]) == 2
    assert bob.put(f"{ROOT}/plans/{beijing['id']}/checklist", json={"revision": 0, "removed_ids": []}).status_code == 403
    original = beijing
    beijing = dispatch(operator, beijing)
    dispatch(operator, original)
    shanghai = dispatch(operator, shanghai, [shanghai["items"][0]["id"]])
    board = alice.get("/api/board-tasks").json()
    assert sorted(card["name"] for card in board["tasks"]) == ["【上海局】仅上海配置", "【北京局】执行 SQL"]
    assert success(operator, beijing).status_code == 409

    changed = alice.put(f"{ROOT}/memos/{memo_id}", json={**body, "notes": "已核对脚本"})
    assert changed.status_code == 200, changed.text
    board = alice.get("/api/board-tasks").json()
    card = next(row for row in board["tasks"] if row["deployment_plan_id"] == beijing["id"])
    assert card["notes"] == "已核对脚本"
    card_path = f"/api/board-tasks/{card['id']}"
    response = alice.patch(f"{card_path}?revision={card['revision']}&week_start={board['current_week']}", json={"notes": "覆盖"})
    assert response.status_code == 409
    item_path = f"{ROOT}/plans/{beijing['id']}/items/{beijing['items'][0]['id']}"
    assert bob.patch(item_path, json={"done": True}).status_code == 404
    response = alice.patch(f"{card_path}/status", json={"state": "done", "revision": card["revision"], "week_start": board["current_week"]})
    assert response.status_code == 200, response.text
    card = response.json()
    beijing = details(operator, beijing)
    assert beijing["items"][0]["done"]
    week_path = f"/api/weeks/{board['current_week']}"
    week = alice.get(week_path).json()
    task, = week["tasks"]
    assert task["deployment_plan_id"] == beijing["id"]
    response = alice.patch(f"{week_path}/tasks/{task['id']}?revision={week['revision']}", json={"status": "50%"})
    assert response.status_code == 200, response.text
    assert not details(operator, beijing)["items"][0]["done"]
    response = alice.patch(item_path, json={"done": True})
    assert response.status_code == 200, response.text
    beijing = response.json()
    assert alice.get(week_path).json()["tasks"][0]["status"] == "已完成"
    card = next(row for row in alice.get("/api/board-tasks").json()["tasks"] if row["id"] == card["id"])
    assert success(operator, beijing).status_code == 200
    archived = next(row for row in alice.get(f"{ROOT}/memos").json() if row["id"] == memo_id)
    assert archived["version"]["number"] == "1.10.0" and not archived["done"]
    assert alice.put(f"{ROOT}/memos/{memo_id}", json=body).status_code == 409
    assert alice.patch(f"{card_path}/status", json={"state": "in_progress", "revision": card["revision"], "week_start": board["current_week"]}).status_code == 409

    shanghai = details(operator, shanghai)
    config_item = shanghai["items"][1]
    complete = alice.patch(f"{ROOT}/plans/{shanghai['id']}/items/{config_item['id']}", json={"done": True})
    assert complete.status_code == 200, complete.text
    assert success(operator, complete.json()).status_code == 200
    beijing_next, shanghai_next, wuhan_next, guangzhou_next = create_plan(operator, project, v3, "beijing", "shanghai", "wuhan", "guangzhou")
    assert not details(operator, beijing_next)["items"]
    assert not details(operator, guangzhou_next)["items"]
    wuhan_next = details(operator, wuhan_next)
    assert wuhan_next["from_version"]["number"] == "1.9.9"
    wuhan_sql, = wuhan_next["items"]
    assert wuhan_sql["source_version"] == "1.10.0"
    wuhan_next = dispatch(operator, wuhan_next)
    response = alice.patch(f"{ROOT}/plans/{wuhan_next['id']}/items/{wuhan_sql['id']}", json={"done": True})
    assert response.status_code == 200, response.text
    assert success(operator, response.json()).status_code == 200
    shanghai_next = details(operator, shanghai_next)
    sql, = shanghai_next["items"]
    assert sql["source_version"] == "1.10.0"
    shanghai_next = dispatch(operator, shanghai_next)
    response = operator.patch(f"{ROOT}/plans/{shanghai_next['id']}/items/{sql['id']}", json={"done": True})
    assert response.status_code == 200, response.text
    assert success(operator, response.json()).status_code == 200
    archived = next(row for row in alice.get(f"{ROOT}/memos").json() if row["id"] == memo_id)
    assert archived["version"]["number"] == "1.10.0" and archived["done"]
    assert next(target for target in archived["targets"] if target["site"] == "guangzhou")["baseline_covered"]
    history = alice.get(f"{ROOT}/plans?history=true&project_id={project}&site=shanghai&version=1.11.0").json()
    assert [row["id"] for row in history] == [shanghai_next["id"]]


def test_checklist_refresh_then_withdraw(gitlab_main):
    operator, member = client("admin"), client("alice")
    project = project_for(operator, "national")
    version = version_for(operator, project, "1.0.0")
    plan, = create_plan(operator, project, version, "national")
    memo = member.post(f"{ROOT}/memos", json={"project_id": project, "title": "修改配置"})
    assert memo.status_code == 201, memo.text
    assert operator.put(f"{ROOT}/plans/{plan['id']}/checklist", json={"revision": 0, "removed_ids": []}).status_code == 409
    refresh = operator.post(f"{ROOT}/plans/{plan['id']}/checklist/refresh", json={"revision": 0})
    assert refresh.status_code == 200, refresh.text
    plan = dispatch(operator, refresh.json())
    assert len(member.get("/api/board-tasks").json()["tasks"]) == 1
    plan = dispatch(operator, plan, [plan["items"][0]["id"]])
    assert member.get("/api/board-tasks").json()["tasks"] == []
    assert success(operator, plan).status_code == 200
    assert member.get(f"{ROOT}/memos").json()[0]["version"] is None


def test_gitlab_refs_are_queried_validated_and_saved(monkeypatch):
    class Response:
        headers = {"X-Next-Page": "2"}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps(self.payload)

    calls = []

    def open_request(request, timeout):
        calls.append(request)
        url = urlsplit(request.full_url)
        kind = "branches" if "/branches" in url.path else "tags"
        name = "release/1.2.3" if kind == "branches" else "prod/1.2.3"
        ref = {"name": name, "commit": {"id": ("a" if kind == "branches" else "b") * 40}}
        if url.query:
            return Response([ref])
        if unquote(url.path.split("/")[-1]) != name:
            raise HTTPError(request.full_url, 404, "Missing ref", None, None)
        return Response(ref)

    base = "https://gitlab.example.com"
    monkeypatch.setenv("REVIEW_GITLAB_URLS", base)
    monkeypatch.setenv("DEPLOYMENT_GITLAB_TOKENS", json.dumps({base: "test-only"}))
    monkeypatch.setattr(deployments, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    operator = client("admin")
    project = operator.post("/api/reviews/projects", json={
        "name": "带标签的项目", "url": f"{base}/team/app", "gitlab_url": base, "gitlab_id": 15,
        "deployment_level": "national", "deployment_network": "internal",
    }).json()["id"]
    path = f"{ROOT}/projects/{project}"
    branches = operator.get(f"{path}/branches", params={"page": 2, "search": "release/"}).json()
    tags = operator.get(f"{path}/tags", params={"page": 2, "search": "prod/"}).json()
    assert branches["has_more"] and branches["items"][0]["name"] == "release/1.2.3"
    assert tags["has_more"] and tags["items"][0]["name"] == "prod/1.2.3"
    assert "search=release%2F&page=2" in calls[0].full_url
    assert "search=prod%2F&page=2" in calls[1].full_url
    assert client("alice").get(f"{path}/tags").status_code == 403
    payload = {"number": "1.2.3", "branch": "release/1.2.3", "sha": "a" * 40,
               "tag": "prod/1.2.3", "tag_sha": "b" * 40}
    for endpoint, number in (("baseline-versions", "1.2.3"), ("versions", "1.2.4")):
        data = {**payload, "number": number}
        assert operator.post(f"{path}/{endpoint}", json={**data, "branch": "unknown"}).status_code == 422
        assert operator.post(f"{path}/{endpoint}", json={**data, "tag": "unknown"}).status_code == 422
        assert operator.post(f"{path}/{endpoint}", json={**data, "tag_sha": "c" * 40}).status_code == 409
        response = operator.post(f"{path}/{endpoint}", json=data)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["tag"] == payload["tag"] and saved["tag_sha"] == payload["tag_sha"]
        assert saved["tag_url"].endswith("/-/tags/prod%2F1.2.3")
        assert calls[-2].full_url.endswith("/branches/release%2F1.2.3")
        assert calls[-1].full_url.endswith("/tags/prod%2F1.2.3")
        assert calls[-1].get_header("Private-token") == "test-only"
    assert operator.get(f"{path}/versions").json()[0] == saved
