from .test_api import clean_db, client, mutate
from .test_meeting_assignments import current_week


def test_common_review_projects_are_shared_and_only_admin_can_change_them():
    admin, alice = client("admin"), client("alice")
    projects = "/api/reviews/projects"
    payload = {"name": "Demo", "url": "https://git.example.com/team/demo"}
    project = admin.post(projects, json={**payload, "visibility": "internal", "owner": "legacy-team"}).json()
    assert project["is_common"] is False
    path = f"{projects}/{project['id']}"
    day = "/api/reviews/days/2026-11-12"
    assert alice.get(day).json()["common_project_ids"] == []
    assert alice.patch(path, json={"is_common": True}).status_code == 403
    assert admin.patch(path, json={"is_common": True}).json()["is_common"] is True
    edited = admin.put(path, json={**payload, "alias": "新别名"}).json()
    assert edited["is_common"] is True
    assert (edited["visibility"], edited["owner"]) == ("internal", "legacy-team")
    assert alice.get(day).json()["common_project_ids"] == [project["id"]]
    assert admin.patch(path, json={"is_common": False}).json()["is_common"] is False
    assert alice.get(day).json()["common_project_ids"] == []


def test_daily_report_is_retry_safe_and_syncs_issue_status_with_weekly_task(monkeypatch):
    admin, alice, bob = client("admin"), client("alice"), client("bob")
    projects = "/api/reviews/projects"
    payload = {"name": "Demo", "url": "https://git.example.com/team/demo", "owner": "team"}
    assert alice.post(projects, json=payload).status_code == 403
    project = admin.post(projects, json=payload).json()
    assert project["alias"] == "Demo" and project["skip_slash_branches"] is True
    monkeypatch.setenv("REVIEW_WORKER_TOKEN", "local-test-worker-token")
    worker = "/api/reviews/worker"
    worker_headers = {"Authorization": "Bearer local-test-worker-token"}
    assert admin.get(f"{worker}/projects").status_code == 401
    assert admin.get(f"{worker}/projects", headers=worker_headers).json()["projects"] == [project]

    project_id = project["id"]
    issue = {"project_id": project_id, "fingerprint": "a" * 64, "author": "alice", "title": "检查空值",
             "severity": "高危", "sha": "abcd", "commit_message": "commit", "risk": "可能抛异常"}
    data = {"report_date": "2026-11-12", "commit_date": "2026-11-11", "model": "model", "duration_seconds": 14,
            "projects": [{"project_id": project_id, "alias": project["alias"], "commits": [], "positives": ["增加单元测试"]}],
            "issues": [issue, {**issue, "fingerprint": "b" * 64, "author": "unknown", "severity": "低危"}]}
    assert admin.post(f"{worker}/reports", json=data, headers=worker_headers).status_code == 200
    day = "/api/reviews/days/2026-11-12"
    marks = "/api/calendar/marks?year=2026&scope=review-records"
    empty_report = {**data, "report_date": "2026-11-13", "commit_date": "2026-11-12", "issues": []}
    assert admin.post(f"{worker}/reports", json=empty_report, headers=worker_headers).status_code == 200
    assert alice.get(f"{marks}&month=11").json() == ["2026-11-12", "2026-11-13"]
    assert alice.get(f"{marks}&month=11&include_issue_counts=true").json() == [
        {"date": "2026-11-12", "issue_count": 2},
        {"date": "2026-11-13", "issue_count": 0},
    ]
    assert alice.get(f"{marks}&month=10&include_issue_counts=true").json() == []
    daily = alice.get(day).json()
    assert daily["summary"]["model"] == "model"
    mine, unknown = daily["issues"]
    assert mine["mine"] and mine["author_name"] == "小王" and unknown["anonymous"]
    issue_path = f"/api/reviews/issues/{mine['id']}"
    assert alice.post(f"{issue_path}/task").status_code == 200
    assert bob.post(f"{issue_path}/task").status_code == 200
    assert bob.get(f"/api/weeks/{current_week()}").json()["tasks"] == []
    week = f"/api/weeks/{current_week()}"
    weekly = alice.get(week).json()
    task, = weekly["tasks"]
    assert (task["category_name"], task["task_group"], task["description"]) == ("开发相关", "修改代码审查问题", "检查空值")
    assert task["work_days"] == [] and task["review_issue_id"] == mine["id"]
    assert alice.patch(issue_path, json={"status": "忽略", "notes": "  "}).status_code == 422
    assert alice.patch(issue_path, json={"status": "忽略", "notes": "误报"}).status_code == 200
    assert alice.get(week).json()["tasks"][0]["status"] == "忽略"
    task_path = f"{week}/tasks/{task['id']}"
    assert mutate(alice, "PATCH", task_path, weekly["revision"], {"status": "已完成"}).status_code == 409
    assert mutate(alice, "PATCH", task_path, weekly["revision"] + 1, {"status": "已完成"}).status_code == 200
    assert alice.patch(issue_path, json={"notes": "追加备注"}).json()["status"] == "已完成"
    assert alice.get(week).json()["revision"] == weekly["revision"] + 2
    data["issues"][0].update(title="检查缺少的空值判断", risk="缺少判空时会抛异常", suggestion="调用前先判断参数是否为空。")
    assert admin.post(f"{worker}/reports", json=data, headers=worker_headers).status_code == 200
    updated = alice.get(day).json()["issues"]
    assert len(updated) == 2 and updated[0]["id"] == mine["id"] and updated[0]["status"] == "已完成"
    assert updated[0]["notes"] == "追加备注" and updated[0]["task_added"]
    detail = alice.get(issue_path).json()
    assert detail == {**updated[0], "project_alias": project["alias"]}
    assert updated[0]["title"] == "检查缺少的空值判断" and updated[0]["suggestion"] == "调用前先判断参数是否为空。"
    alice_messages = alice.get("/api/notifications").json()["items"]
    assert len(alice_messages) == 1 and alice_messages[0]["target"] == {"date": "2026-11-12"}
    assert admin.patch(f"{projects}/{project_id}", json={"is_common": True}).status_code == 200
    assert alice.get(day).json()["common_project_ids"] == [project_id]
    assert admin.delete(f"{projects}/{project_id}").status_code == 200
    assert admin.get(projects).json() == []
    historical = alice.get(day).json()
    assert historical["projects"] == {str(project_id): "Demo"}
    assert historical["common_project_ids"] == []


def test_transfer_notification_access_filters_and_read_state():
    admin, alice, bob = client("admin"), client("alice"), client("bob")
    week_start = current_week()
    week = f"/api/weeks/{week_start}"
    state = mutate(alice, "POST", f"{week}/tasks", 0).json()
    task_id = state["tasks"][0]["id"]
    bob_id = alice.get("/api/task-transfer-recipients").json()[0]["id"]
    assert mutate(alice, "POST", f"{week}/tasks/{task_id}/transfer", state["revision"], {"user_id": bob_id}).status_code == 200
    path = "/api/notifications"
    message, = bob.get(path).json()["items"]
    board_task, = bob.get("/api/board-tasks").json()["tasks"]
    assert message["target"] == {"board_task": board_task["id"]} and message["is_read"] is False
    assert alice.patch(f"{path}/{message['id']}", json={"is_read": True}).status_code == 404
    assert alice.get(f"{path}?all_users=true").status_code == 403
    assert bob.get(f"{path}/unread").json() == {"count": 1}
    assert bob.patch(f"{path}/{message['id']}", json={"is_read": True}).status_code == 200
    assert bob.get(f"{path}/unread").json() == {"count": 0}
    overview, = admin.get(path, params={"all_users": True, "is_read": True, "kind": "转交任务"}).json()["items"]
    assert overview["recipient"] == "小李" and "target" not in overview
    assert admin.get(path, params={"all_users": True, "day": "2000-01-01"}).json()["total"] == 0
    assert bob.patch(f"{path}/{message['id']}", json={"is_read": False}).status_code == 200
    assert bob.get(f"{path}/unread").json() == {"count": 1}
