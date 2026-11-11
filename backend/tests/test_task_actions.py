from .test_api import client, clean_db, mutate
from .test_meeting_assignments import current_week, editable, setup_assignment


def test_transfer_moves_one_task_and_updates_both_revisions():
    alice, bob, admin = client("alice"), client("bob"), client("admin")
    week = f"/api/weeks/{current_week()}"
    people = alice.get("/api/task-transfer-recipients").json()
    assert [person["username"] for person in people] == ["bob"]
    bob_id = people[0]["id"]
    alice_id = bob.get("/api/task-transfer-recipients").json()[0]["id"]
    admin_id = next(user["id"] for user in admin.get("/api/users").json() if user["role"] == "admin")
    source = mutate(alice, "POST", f"{week}/tasks", 0).json()
    task = source["tasks"][0]
    assert task["priority"] is None and task["transferred_by"] is None
    path = f"{week}/tasks/{task['id']}"
    assert mutate(alice, "PATCH", path, 1, {"priority": "紧急"}).status_code == 422
    assert mutate(alice, "PATCH", path, 1, {"priority": "高", "description": "转交测试", "status": "50%", "work_days": [2]}).status_code == 200
    source = mutate(alice, "POST", f"{week}/tasks", 2).json()
    target = mutate(bob, "POST", f"{week}/tasks", 0).json()
    for user_id in (admin_id, alice_id):
        assert mutate(alice, "POST", f"{path}/transfer", source["revision"], {"user_id": user_id}).status_code == 422
    assert mutate(bob, "POST", f"{path}/transfer", target["revision"], {"user_id": alice_id}).status_code == 404
    assert mutate(alice, "POST", f"{path}/transfer", 1, {"user_id": bob_id}).status_code == 409
    result = mutate(alice, "POST", f"{path}/transfer", source["revision"], {"user_id": bob_id})
    assert result.status_code == 200, result.text
    assert result.json()["tasks"] == [{**source["tasks"][1], "position": 1}]
    received = bob.get(week).json()
    assert received["tasks"] == [target["tasks"][0], {
        **source["tasks"][0], "position": 2, "transferred_by": "小王",
    }]
    assert received["revision"] == target["revision"] + 1
    assert mutate(bob, "PATCH", path, target["revision"], {"priority": None}).status_code == 409
    assert mutate(bob, "PATCH", path, received["revision"], {"priority": None}).json()["tasks"][1]["priority"] is None


def test_meeting_task_transfer_keeps_the_link_and_rejects_duplicate_assignee():
    alice, bob, meeting = setup_assignment()
    meeting_path = f"/api/meetings/{meeting['id']}"
    week = f"/api/weeks/{current_week()}"
    source = alice.get(week).json()
    task = source["tasks"][0]
    bob_id = alice.get("/api/task-transfer-recipients").json()[0]["id"]
    path = f"{week}/tasks/{task['id']}/transfer"
    assert mutate(alice, "POST", path, source["revision"], {"user_id": bob_id}).status_code == 409
    assert alice.get(week).json() == source
    payload = editable(meeting)
    payload["tasks"][0]["assignments"] = [
        item for item in payload["tasks"][0]["assignments"] if item["user_id"] != bob_id
    ]
    saved = alice.put(meeting_path, json=payload).json()
    source = alice.get(week).json()
    assert mutate(alice, "POST", path, source["revision"], {"user_id": bob_id}).status_code == 200
    assert bob.get(week).json()["tasks"][0]["meeting_task_id"] == task["meeting_task_id"]
    updated = alice.get(meeting_path).json()
    assert updated["revision"] == saved["revision"] + 1
    assert [(assignment["user_id"], assignment["status"]) for assignment in updated["tasks"][0]["assignments"]] == [(bob_id, "50%")]
