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
    changed = mutate(alice, "PATCH", f"{week}/tasks/{task_id}", a["revision"], {"description": "长描述" * 600, "status": "已完成"})
    assert changed.status_code == 200, changed.text
    assert bob.get(week).json()["tasks"][0]["description"] == "长描述" * 600
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
    changed = mutate(alice, "PATCH", f"{week}/tasks/{old['id']}", copied["revision"], {"description": "独立旧任务"}).json()
    assert alice.get(path).json()["tasks"][0]["name"] != "独立旧任务"
    assert alice.delete(path).status_code == 200
    remaining = alice.get(week).json()
    assert [t["id"] for t in remaining["tasks"]] == [old["id"]]
    assert bob.get(week).json()["tasks"] == []
    assert mutate(alice, "DELETE", f"{week}/tasks/{old['id']}", remaining["revision"]).status_code == 200


def test_carry_transfers_only_current_link_and_protects_overwrite():
    alice, bob, meeting = setup_assignment()
    source = f"/api/weeks/{current_week()}"
    target = f"/api/weeks/{current_week() + timedelta(days=7)}"
    old = alice.get(source).json()
    copied = mutate(alice, "POST", f"{target}/carry-over", 0, {"mode": "append"}).json()
    assert copied["tasks"][0]["meeting_task_id"]
    assert alice.get(source).json()["tasks"][0]["meeting_task_id"] is None
    assert alice.get(source).json()["revision"] > old["revision"]
    assert mutate(alice, "POST", f"{target}/carry-over", copied["revision"], {"mode": "overwrite"}).status_code == 409
    new = copied["tasks"][0]
    assert mutate(alice, "PATCH", f"{target}/tasks/{new['id']}", copied["revision"], {"description": "新周描述", "status": "90%"}).status_code == 200
    current = alice.get(f"/api/meetings/{meeting['id']}").json()
    assert current["tasks"][0]["name"] == "新周描述"
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
