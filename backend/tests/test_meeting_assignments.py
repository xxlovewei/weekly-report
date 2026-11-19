from datetime import datetime, timedelta, timezone
from .test_api import client, clean_db, mutate


def current_week():
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return today - timedelta(days=today.weekday())


def setup_assignment():
    alice, bob = client("alice"), client("bob")
    people = alice.get("/api/meeting-assignees").json()
    assert {p["username"] for p in people} == {"alice", "bob"}
    payload = {"meeting_date": "2020-01-01", "meeting_type": "周会", "content": "指派测试", "needs_follow_up": True,
               "tasks": [{"name": "共同描述", "status": None, "assignments": [{"user_id": p["id"], "status": "50%" if p["username"] == "alice" else None} for p in people]}]}
    result = alice.post("/api/meetings", json=payload)
    assert result.status_code == 201, result.text
    return alice, bob, result.json()


def editable(meeting):
    return {k: ([{key: ([{"user_id": a["user_id"], "status": a["status"]} for a in t["assignments"]] if key == "assignments" else t[key]) for key in ("id", "name", "status", "assignments")} for t in v] if k == "tasks" else v)
            for k, v in meeting.items() if k in {"revision", "meeting_date", "meeting_type", "content", "needs_follow_up", "tasks"}}


def test_new_assignees_receive_one_notification_with_their_work_target(monkeypatch):
    alice, bob = client("alice"), client("bob")
    people = {p["username"]: p["id"] for p in alice.get("/api/meeting-assignees").json()}
    assignment_filter = {"kind": "会议指派", "is_read": False}
    week = f"/api/weeks/{current_week()}"
    date = "2020-01-01"
    created = alice.post("/api/meetings", json={
        "meeting_date": date, "meeting_type": "周会", "content": "指派通知", "needs_follow_up": True,
        "tasks": [{"name": "跟进联调", "assignments": [{"user_id": people["alice"]}]}],
    })
    assert created.status_code == 201, created.text
    meeting = created.json()
    path = f"/api/meetings/{meeting['id']}"
    assert alice.get("/api/notifications/unread").json() == {"count": 1}
    assert bob.get("/api/notifications/unread").json() == {"count": 0}

    payload = editable(meeting)
    payload["tasks"][0]["assignments"].extend([{"user_id": people["bob"]}, {"user_id": 1}])
    assert alice.put(path, json=payload).status_code == 422
    assert bob.get(week).json()["tasks"] == []
    assert bob.get("/api/notifications/unread").json() == {"count": 0}
    payload["tasks"][0]["assignments"].pop()
    saved = alice.put(path, json=payload)
    assert saved.status_code == 200, saved.text
    updated = editable(saved.json())
    updated["tasks"][0]["assignments"][0]["status"] = "50%"
    assert alice.put(path, json=updated).status_code == 200

    for assignee in (alice, bob):
        task, = assignee.get(week).json()["tasks"]
        assert task["meeting_id"] == meeting["id"]
        assert task["meeting_date"] == date
        response = assignee.get("/api/notifications", params=assignment_filter)
        assert response.status_code == 200, response.text
        message, = response.json()["items"]
        assert message["kind"] == "会议指派" and "跟进联调" in message["title"]
        assert message["target"] == {"week": str(current_week()), "task": task["id"]}

    bob_week = bob.get(week).json()
    copied = mutate(bob, "POST", f"{week}/tasks/{bob_week['tasks'][0]['id']}/duplicate", bob_week["revision"]).json()
    old, current = copied["tasks"]
    assert old["meeting_id"] is None and current["meeting_id"] == meeting["id"]
    message, = bob.get("/api/notifications", params=assignment_filter).json()["items"]
    assert message["target"]["task"] == current["id"]

    next_week = current_week() + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: next_week)
    carried = mutate(bob, "POST", f"/api/weeks/{next_week}/carry-over", 0, {"mode": "append"}).json()
    linked, = (task for task in carried["tasks"] if task["meeting_id"])
    message, = bob.get("/api/notifications", params=assignment_filter).json()["items"]
    assert message["target"] == {"week": str(next_week), "task": linked["id"]}


def test_assignment_sync_copy_delete_and_conflicts():
    alice, bob, meeting = setup_assignment()
    path = f"/api/meetings/{meeting['id']}"
    week = f"/api/weeks/{current_week()}"
    a = alice.get(week).json()
    b = bob.get(week).json()
    assert len(a["tasks"]) == len(b["tasks"]) == 1
    assert a["tasks"][0]["status"] == "50%" and b["tasks"][0]["status"] is None
    task_id = a["tasks"][0]["id"]
    assert mutate(alice, "DELETE", f"{week}/tasks/{task_id}", a["revision"]).status_code == 403
    changed = mutate(alice, "PATCH", f"{week}/tasks/{task_id}", a["revision"], {"task_group": "新名称", "description": "长描述" * 600, "status": "已完成"})
    assert changed.status_code == 200, changed.text
    assert bob.get(week).json()["tasks"][0]["task_group"] == "新名称"
    assert bob.get(week).json()["tasks"][0]["description"] == ""
    assert bob.get(week).json()["tasks"][0]["status"] is None
    assert alice.put(path, json=editable(meeting)).status_code == 409
    meeting = alice.get(path).json()
    payload = editable(meeting)
    bob_id = next(a["user_id"] for a in meeting["tasks"][0]["assignments"] if a["person"]["username"] == "bob")
    next(a for a in payload["tasks"][0]["assignments"] if a["user_id"] == bob_id)["status"] = "80%"
    saved = alice.put(path, json=payload)
    assert saved.status_code == 200, saved.text
    assert alice.put(path, json=editable(saved.json())).status_code == 200
    assert len(alice.get(week).json()["tasks"]) == 1
    assert bob.get(week).json()["tasks"][0]["status"] == "80%"
    assert bob.get("/api/meetings?status=80%25").json()["total"] == 1
    a = alice.get(week).json()
    copied = mutate(alice, "POST", f"{week}/tasks/{task_id}/duplicate", a["revision"], key="copy-linked").json()
    old, new = copied["tasks"]
    assert old["meeting_task_id"] is None and new["meeting_task_id"]
    assert mutate(alice, "POST", f"{week}/tasks/{task_id}/duplicate", a["revision"], key="copy-linked").json() == copied
    changed = mutate(alice, "PATCH", f"{week}/tasks/{old['id']}", copied["revision"], {"task_group": "独立旧任务"}).json()
    assert alice.get(path).json()["tasks"][0]["name"] != "独立旧任务"
    assert alice.delete(path).status_code == 200
    remaining = alice.get(week).json()
    assert [t["id"] for t in remaining["tasks"]] == [old["id"]]
    assert bob.get(week).json()["tasks"] == []
    assert mutate(alice, "DELETE", f"{week}/tasks/{old['id']}", remaining["revision"]).status_code == 200


def test_carry_transfers_only_current_link_and_protects_overwrite(monkeypatch):
    alice, bob, meeting = setup_assignment()
    source = f"/api/weeks/{current_week()}"
    next_week = current_week() + timedelta(days=7)
    target = f"/api/weeks/{next_week}"
    monkeypatch.setattr("app.main.current_work_week", lambda: next_week)
    old = alice.get(source).json()
    copied = mutate(alice, "POST", f"{target}/carry-over", 0, {"mode": "append"}).json()
    assert copied["tasks"][0]["meeting_task_id"]
    assert alice.get(source).json()["tasks"][0]["meeting_task_id"] is None
    assert alice.get(source).json()["revision"] > old["revision"]
    assert mutate(alice, "POST", f"{target}/carry-over", copied["revision"], {"mode": "overwrite"}).status_code == 409
    new = copied["tasks"][0]
    assert mutate(alice, "PATCH", f"{target}/tasks/{new['id']}", copied["revision"], {"task_group": "新周名称", "status": "90%"}).status_code == 200
    current = alice.get(f"/api/meetings/{meeting['id']}").json()
    assert current["tasks"][0]["name"] == "新周名称"
    payload = editable(current)
    payload["tasks"][0]["assignments"] = []
    assert alice.put(f"/api/meetings/{meeting['id']}", json=payload).status_code == 200
    assert alice.get(target).json()["tasks"] == []
    assert len(alice.get(source).json()["tasks"]) == 1
    assert bob.get(source).json()["tasks"] == []


def test_assignment_validation_and_removing_task():
    alice, bob, meeting = setup_assignment()
    path = f"/api/meetings/{meeting['id']}"
    payload = editable(meeting)
    payload["tasks"][0]["assignments"].append({"user_id": 1, "status": None})
    assert alice.put(path, json=payload).status_code == 422
    payload = editable(meeting)
    payload["tasks"][0]["assignments"].append(payload["tasks"][0]["assignments"][0])
    assert alice.put(path, json=payload).status_code == 422
    payload = editable(meeting)
    payload["tasks"][0]["id"] = 99999
    assert alice.put(path, json=payload).status_code == 422
    payload = editable(meeting)
    payload["needs_follow_up"], payload["tasks"] = False, []
    assert alice.put(path, json=payload).status_code == 200
    assert alice.get(f"/api/weeks/{current_week()}").json()["tasks"] == []
    assert bob.get(f"/api/weeks/{current_week()}").json()["tasks"] == []


def test_assignment_migration_fresh_and_existing(monkeypatch):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from .test_api import engine
    migration = import_module("migrations.versions.0007_meeting_assignments")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.downgrade()
        migration.upgrade()
        assert "meeting_task_id" in {c["name"] for c in inspect(connection).get_columns("tasks")}


def test_legacy_long_meeting_name_is_displayed_and_preserved_until_renamed():
    from app.db import SessionLocal
    from app.models import MeetingTask, Task
    from sqlalchemy import select

    alice, _, meeting = setup_assignment()
    legacy_name = "旧会议任务" * 100
    meeting_task_id = meeting["tasks"][0]["id"]
    with SessionLocal() as db:
        db.get(MeetingTask, meeting_task_id).name = legacy_name
        for detail in db.scalars(select(Task).where(Task.meeting_task_id == meeting_task_id)):
            detail.task_group = ""
            detail.description = legacy_name
        db.commit()
    week_path = f"/api/weeks/{current_week()}"
    detail, = alice.get(week_path).json()["tasks"]
    assert detail["task_group"] == legacy_name
    meeting_path = f"/api/meetings/{meeting['id']}"
    payload = editable(alice.get(meeting_path).json())
    saved = alice.put(meeting_path, json={**payload, "content": "仅更新会议内容"})
    assert saved.status_code == 200, saved.text
    payload = editable(saved.json())
    payload["tasks"][0]["name"] = legacy_name + "修改"
    assert alice.put(meeting_path, json=payload).status_code == 422
    payload["tasks"][0]["name"] = "新的任务名称"
    assert alice.put(meeting_path, json=payload).status_code == 200
    detail, = alice.get(week_path).json()["tasks"]
    assert detail["task_group"] == "新的任务名称"
    assert detail["description"] == legacy_name
