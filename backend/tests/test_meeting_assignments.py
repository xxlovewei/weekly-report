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


def start_inbox_task(client, state="in_progress", *, card_id=None):
    board = client.get("/api/board-tasks").json()
    card, = (item for item in board["tasks"] if card_id is None or item["id"] == card_id)
    assert card["state"] == "inbox"
    result = client.patch(f"/api/board-tasks/{card['id']}/status", json={
        "revision": card["revision"], "week_start": board["current_week"], "state": state,
    })
    assert result.status_code == 200, result.text
    return result.json()


def editable(meeting):
    return {k: ([{key: ([{"user_id": a["user_id"], "status": a["status"]} for a in t["assignments"]] if key == "assignments" else t[key]) for key in ("id", "name", "status", "assignments")} for t in v] if k == "tasks" else v)
            for k, v in meeting.items() if k in {"revision", "meeting_date", "meeting_type", "content", "needs_follow_up", "tasks"}}


def test_new_assignees_receive_one_notification_with_their_board_target(monkeypatch):
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
        assert assignee.get(week).json()["tasks"] == []
        card = start_inbox_task(assignee)
        task, = assignee.get(week).json()["tasks"]
        assert task["meeting_id"] == meeting["id"]
        assert task["meeting_date"] == date
        response = assignee.get("/api/notifications", params=assignment_filter)
        assert response.status_code == 200, response.text
        message, = response.json()["items"]
        assert message["kind"] == "会议指派" and "跟进联调" in message["title"]
        assert message["target"] == {"board_task": card["id"]} and task["board_task_id"] == card["id"]

    bob_week = bob.get(week).json()
    copied = mutate(bob, "POST", f"{week}/tasks/{bob_week['tasks'][0]['id']}/duplicate", bob_week["revision"]).json()
    old, current = copied["tasks"]
    assert old["meeting_id"] == meeting["id"] and current["meeting_id"] is None
    message, = bob.get("/api/notifications", params=assignment_filter).json()["items"]
    assert message["target"]["board_task"] == old["board_task_id"]

    next_week = current_week() + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: next_week)
    carried = mutate(bob, "POST", f"/api/weeks/{next_week}/add-in-progress", 0).json()
    linked, = (task for task in carried["tasks"] if task["meeting_id"])
    message, = bob.get("/api/notifications", params=assignment_filter).json()["items"]
    assert message["target"] == {"board_task": linked["board_task_id"]}


def test_assignment_sync_copy_delete_and_conflicts():
    alice, bob, meeting = setup_assignment()
    path = f"/api/meetings/{meeting['id']}"
    week = f"/api/weeks/{current_week()}"
    start_inbox_task(alice)
    start_inbox_task(bob)
    meeting = alice.get(path).json()
    a = alice.get(week).json()
    b = bob.get(week).json()
    assert len(a["tasks"]) == len(b["tasks"]) == 1
    assert a["tasks"][0]["status"] == "50%" and b["tasks"][0]["status"] == "5%"
    assert a["tasks"][0]["name_locked"] and b["tasks"][0]["name_locked"]
    task_id = a["tasks"][0]["id"]
    assert mutate(alice, "DELETE", f"{week}/tasks/{task_id}", a["revision"]).status_code == 403
    assert mutate(alice, "PATCH", f"{week}/tasks/{task_id}", a["revision"], {"task_group": "新名称"}).status_code == 409
    changed = mutate(alice, "PATCH", f"{week}/tasks/{task_id}", a["revision"], {"description": "长描述" * 600, "status": "已完成"})
    assert changed.status_code == 200, changed.text
    assert bob.get(week).json()["tasks"][0]["task_group"] == "共同描述"
    assert bob.get(week).json()["tasks"][0]["description"] == ""
    assert bob.get(week).json()["tasks"][0]["status"] == "5%"
    assert alice.put(path, json=editable(meeting)).status_code == 409
    meeting = alice.get(path).json()
    assert next(a for a in meeting["tasks"][0]["assignments"] if a["person"]["username"] == "alice")["status"] == "已完成"
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
    assert old["meeting_task_id"] and new["meeting_task_id"] is None
    assert mutate(alice, "POST", f"{week}/tasks/{task_id}/duplicate", a["revision"], key="copy-linked").json() == copied
    assert mutate(alice, "PATCH", f"{week}/tasks/{new['id']}", copied["revision"], {"task_group": "独立任务"}).status_code == 200
    assert alice.get(path).json()["tasks"][0]["name"] != "独立任务"
    assert alice.delete(path).status_code == 200
    remaining = alice.get(week).json()
    assert [t["id"] for t in remaining["tasks"]] == [new["id"]]
    assert bob.get(week).json()["tasks"] == []
    assert mutate(alice, "DELETE", f"{week}/tasks/{new['id']}", remaining["revision"]).status_code == 200


def test_add_in_progress_retains_meeting_history_and_does_not_duplicate(monkeypatch):
    alice, bob, meeting = setup_assignment()
    start_inbox_task(alice)
    source = f"/api/weeks/{current_week()}"
    next_week = current_week() + timedelta(days=7)
    target = f"/api/weeks/{next_week}"
    monkeypatch.setattr("app.main.current_work_week", lambda: next_week)
    old = alice.get(source).json()
    copied = mutate(alice, "POST", f"{target}/add-in-progress", 0).json()
    assert copied["tasks"][0]["meeting_task_id"]
    old["tasks"][0]["has_history"] = True
    assert alice.get(source).json() == old
    assert mutate(alice, "POST", f"{target}/add-in-progress", copied["revision"]).json()["no_source"]
    new = copied["tasks"][0]
    assert mutate(alice, "PATCH", f"{target}/tasks/{new['id']}", copied["revision"], {"status": "90%"}).status_code == 200
    current = alice.get(f"/api/meetings/{meeting['id']}").json()
    assert current["tasks"][0]["name"] == "共同描述"
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


def test_inbox_migration_preserves_existing_assignment_detail_and_message(monkeypatch):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from .test_api import engine

    migration = import_module("migrations.versions.0018_task_plans_and_inbox")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        week_id = connection.scalar(text("INSERT INTO weeks (user_id, start_date, revision) VALUES (2, :start, 1) RETURNING id"),
                                    {"start": current_week()})
        meeting_id = connection.scalar(text("""
            INSERT INTO meetings (meeting_date, meeting_type, content, needs_follow_up, revision)
            VALUES (CURRENT_DATE, '周会', '历史记录', true, 1) RETURNING id
        """))
        meeting_task = connection.scalar(text("""
            INSERT INTO meeting_tasks (meeting_id, position, name) VALUES (:meeting, 1, '历史指派') RETURNING id
        """), {"meeting": meeting_id})
        task_id = connection.scalar(text("""
            INSERT INTO tasks (week_id, meeting_task_id, position, task_group, description, status, work_days, notes)
            VALUES (:week, :meeting_task, 1, '历史指派', '已保存的个人进展', '50%', '[]', '') RETURNING id
        """), {"week": week_id, "meeting_task": meeting_task})
        connection.execute(text("""
            INSERT INTO notifications (user_id, kind, title, task_id, is_read)
            VALUES (2, '会议指派', '历史消息', :task, false)
        """), {"task": task_id})
        migration.upgrade()

    alice = client("alice")
    card, = alice.get("/api/board-tasks").json()["tasks"]
    detail, = alice.get(f"/api/weeks/{current_week()}").json()["tasks"]
    message, = alice.get("/api/notifications").json()["items"]
    assert card["meeting_id"] == meeting_id and card["state"] == "in_progress"
    assert detail["id"] == task_id and detail["description"] == "已保存的个人进展"
    assert message["target"] == {"board_task": card["id"]}


def test_legacy_long_meeting_name_is_displayed_and_preserved_until_renamed():
    from app.db import SessionLocal
    from app.models import MeetingTask, Task
    from sqlalchemy import select

    alice, _, meeting = setup_assignment()
    start_inbox_task(alice)
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
