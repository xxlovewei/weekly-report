from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from .test_api import clean_db, client, mutate
from .test_meeting_assignments import current_week


def test_work_week_access_and_admin_member_edit():
    alice, admin = client("alice"), client("admin")
    week = f"/api/weeks/{current_week()}"
    old = f"/api/weeks/{current_week() - timedelta(days=7)}"
    assert alice.get(old).status_code == 200
    assert mutate(alice, "POST", f"{old}/tasks", 0).status_code == 403
    created = mutate(alice, "POST", f"{week}/tasks", 0).json()
    task_id = created["tasks"][0]["id"]
    assert alice.get(f"{week}?user_id=3").status_code == 403
    assert admin.post(f"{week}/tasks?revision=1&user_id=2").status_code == 403
    changed = admin.patch(f"{week}/tasks/{task_id}?revision=1&user_id=2", json={"task_group": "新名称"})
    assert changed.status_code == 200, changed.text
    assert alice.get(week).json()["tasks"][0]["task_group"] == "新名称"
    assert admin.delete(f"{week}/tasks/{task_id}?revision=2&user_id=2").status_code == 200


def test_board_move_and_week_status_sync(monkeypatch):
    alice, bob = client("alice"), client("bob")
    board = "/api/board-tasks"
    week = f"/api/weeks/{current_week()}"
    created = alice.post(board, json={"name": "联调接口", "category_name": "联调联试", "priority": "高"})
    assert created.status_code == 201, created.text
    card = created.json()
    path = f"{board}/{card['id']}/status"
    body = {"state": "done", "revision": card["revision"], "week_start": str(current_week())}
    assert bob.patch(path, json=body).status_code == 404
    moved = alice.patch(path, json=body)
    assert moved.status_code == 200 and moved.json()["status"] == "已完成"
    assert moved.json()["completed_week"] == str(current_week())
    assert alice.patch(path, json=body).status_code == 409
    detail, = (data := alice.get(week).json())["tasks"]
    assert (detail["task_group"], detail["status"], detail["board_task_id"]) == ("联调接口", "已完成", card["id"])
    updated = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", data["revision"], {"status": None})
    assert updated.status_code == 200
    card, = alice.get(board).json()["tasks"]
    assert card["state"] == "inbox" and card["has_current_detail"]
    assert card["completed_week"] is None
    body.update(state="in_progress", revision=card["revision"])
    moved = alice.patch(path, json=body)
    assert moved.status_code == 200 and moved.json()["status"] == "5%"
    detail, = (data := alice.get(week).json())["tasks"]
    assert detail["status"] == "5%"
    updated = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", data["revision"], {"status": "已完成"})
    assert updated.status_code == 200
    completed_week = current_week()
    next_week = completed_week + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: next_week)
    card, = alice.get(board).json()["tasks"]
    edited = alice.patch(f"{board}/{card['id']}?revision={card['revision']}&week_start={next_week}", json={"notes": "跨周补记"})
    assert edited.status_code == 200 and edited.json()["completed_week"] == str(completed_week)
    body.update(state="in_progress", revision=edited.json()["revision"], week_start=str(next_week))
    reopened = alice.patch(path, json=body)
    assert reopened.status_code == 200 and reopened.json()["completed_week"] is None
    body.update(state="done", revision=reopened.json()["revision"])
    recompleted = alice.patch(path, json=body)
    assert recompleted.status_code == 200 and recompleted.json()["completed_week"] == str(next_week)


@pytest.mark.parametrize("state", ["inbox", "in_progress"])
def test_transfer_board_card_sends_one_notification_and_preserves_progress(state):
    alice, bob = client("alice"), client("bob")
    board = "/api/board-tasks"
    start = alice.get(board).json()["current_week"]
    week = f"/api/weeks/{start}"
    bob_id = alice.get("/api/task-transfer-recipients").json()[0]["id"]
    alice_id = bob.get("/api/task-transfer-recipients").json()[0]["id"]
    card = alice.post(board, json={"name": "接口交接", "category_name": "其他", "priority": "高", "notes": "看板交接备注"}).json()
    if state == "in_progress":
        assert alice.patch(f"{board}/{card['id']}/status",
                           json={"state": state, "revision": card["revision"], "week_start": start}).status_code == 200
        source = alice.get(week).json()
        detail, = source["tasks"]
        assert mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", source["revision"], {
            "description": "交接明细", "status": "50%", "work_days": [2],
        }).status_code == 200
        card, = alice.get(board).json()["tasks"]
    source = alice.get(week).json()
    path = f"{board}/{card['id']}/transfer?revision={card['revision']}&week_start={start}"
    assert bob.post(path, json={"user_id": alice_id}).status_code == 404
    assert alice.post(path, json={"user_id": alice_id}).status_code == 422
    for _ in range(2):
        result = alice.post(path, json={"user_id": bob_id}, headers={"Idempotency-Key": "transfer-card"})
        assert result.status_code == 200, result.text
    assert alice.get(board).json()["tasks"] == []
    assert alice.get(week).json()["tasks"] == bob.get(week).json()["tasks"] == []
    assert alice.get(week).json()["revision"] == source["revision"] + (state == "in_progress")
    received, = bob.get(board).json()["tasks"]
    assert (received["name"], received["state"], received["priority"], received["transferred_by"]) == (
        "接口交接", "inbox", "高", "小王")
    assert received["notes"] == "看板交接备注"
    notification, = bob.get("/api/notifications").json()["items"]
    assert notification["kind"] == "转交任务"
    assert notification["target"] == {"board_task": received["id"]}
    reminder = {"id": notification["id"], "card_id": received["id"], "kind": "转交任务"}
    reminder_path = f"{board}/reminders/{notification['id']}"
    assert alice.patch(reminder_path).status_code == 200
    assert bob.get(board).json()["reminders"] == [reminder]
    if state == "in_progress":
        assert bob.patch(f"/api/notifications/{notification['id']}", json={"is_read": True}).status_code == 200
        assert bob.get(board).json()["reminders"] == [reminder]
    assert bob.patch(reminder_path).status_code == 200
    assert bob.patch(reminder_path).status_code == 200
    assert bob.get(board).json()["reminders"] == []
    message, = bob.get("/api/notifications").json()["items"]
    assert message["is_read"] == (state == "in_progress")
    if state == "in_progress":
        assert bob.patch(f"{board}/{received['id']}/status",
                         json={"state": state, "revision": received["revision"], "week_start": start}).status_code == 200
        detail, = bob.get(week).json()["tasks"]
        assert (detail["description"], detail["status"], detail["work_days"], detail["notes"]) == (
            "交接明细", "50%", [2], "看板交接备注")


def test_week_add_copy_rename_and_delete_share_independent_cards():
    alice = client("alice")
    board = "/api/board-tasks"
    week = f"/api/weeks/{current_week()}"
    first = mutate(alice, "POST", f"{week}/tasks", 0, key="add").json()
    assert mutate(alice, "POST", f"{week}/tasks", 0, key="add").json() == first
    original, = first["tasks"]
    card, = alice.get(board).json()["tasks"]
    assert card["id"] == original["board_task_id"] and card["has_current_detail"] and card["state"] == "inbox"
    path = f"{week}/tasks/{original['id']}"
    updated = mutate(alice, "PATCH", path, first["revision"], {
        "task_group": "同步任务", "category_name": "其他", "priority": "高",
        "status": "已完成", "description": "完成验证",
    }).json()
    copied = mutate(alice, "POST", f"{path}/duplicate", updated["revision"], key="copy").json()
    assert mutate(alice, "POST", f"{path}/duplicate", updated["revision"], key="copy").json() == copied
    _, second = copied["tasks"]
    cards = alice.get(board).json()["tasks"]
    assert {item["id"] for item in cards} == {original["board_task_id"], second["board_task_id"]}
    assert all((item["name"], item["category_name"], item["priority"]) == ("同步任务", "其他", "高") for item in cards)
    states = {item["id"]: item["state"] for item in cards}
    assert states == {original["board_task_id"]: "done", second["board_task_id"]: "inbox"}
    remove = mutate(alice, "DELETE", f"{week}/tasks/{second['id']}", copied["revision"])
    assert remove.status_code == 200, remove.text
    assert [task["id"] for task in remove.json()["tasks"]] == [original["id"]]
    cards = {item["id"]: item for item in alice.get(board).json()["tasks"]}
    assert cards[original["board_task_id"]]["has_current_detail"]
    assert not cards[second["board_task_id"]]["has_current_detail"]
    prepended = mutate(alice, "POST", f"{week}/tasks", remove.json()["revision"]).json()["tasks"]
    assert [task["position"] for task in prepended] == [1, 2]
    assert prepended[1]["id"] == original["id"]


def test_board_notes_follow_task_and_sync_with_current_detail(monkeypatch):
    alice = client("alice")
    board = "/api/board-tasks"
    start = current_week()
    week = f"/api/weeks/{start}"
    fields = {"name": "多行\n任务名称", "category_name": "其他", "priority": "低", "notes": "备注\n第二行"}
    card = alice.post(board, json=fields).json()
    path = f"{board}/{card['id']}"
    moved = alice.patch(f"{path}/status", json={"state": "in_progress", "revision": card["revision"], "week_start": str(start)}).json()
    data = alice.get(week).json()
    detail, = data["tasks"]
    assert (detail["task_group"], detail["notes"]) == (fields["name"], fields["notes"])
    card = alice.patch(f"{path}?revision={moved['revision']}&week_start={start}", json={"notes": "看板补充\n复核"}).json()
    data = alice.get(week).json()
    assert data["tasks"][0]["notes"] == "看板补充\n复核"
    changed = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", data["revision"], {"notes": "明细补充"}).json()
    assert changed["tasks"][0]["notes"] == "明细补充"
    card, = alice.get(board).json()["tasks"]
    assert card["notes"] == "明细补充"

    following = start + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: following)
    next_week = f"/api/weeks/{following}"
    added = mutate(alice, "POST", f"{next_week}/add-in-progress", 0).json()
    assert added["tasks"][0]["notes"] == "明细补充"
    card, = alice.get(board).json()["tasks"]
    cleared = alice.patch(f"{path}?revision={card['revision']}&week_start={following}", json={"notes": ""}).json()
    assert cleared["has_other_details"] and cleared["notes"] == ""
    assert alice.get(next_week).json()["tasks"][0]["notes"] == ""
    assert alice.get(week).json()["tasks"][0]["notes"] == "明细补充"


def test_week_history_locks_rename_and_delete_but_allows_progress_and_copy(monkeypatch):
    alice, admin = client("alice"), client("admin")
    previous = current_week()
    week = f"/api/weeks/{previous}"
    created = mutate(alice, "POST", f"{week}/tasks", 0).json()
    original, = created["tasks"]
    assert mutate(alice, "PATCH", f"{week}/tasks/{original['id']}", created["revision"], {
        "task_group": "跨周任务", "status": "40%", "description": "上周进展",
    }).status_code == 200
    current = previous + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: current)
    current_path = f"/api/weeks/{current}"
    board = "/api/board-tasks"
    assert alice.get(board).json()["tasks"][0]["status"] == "40%"
    existing = mutate(alice, "POST", f"{current_path}/tasks", 0).json()
    existing_task, = existing["tasks"]
    existing = mutate(alice, "PATCH", f"{current_path}/tasks/{existing_task['id']}", existing["revision"], {
        "task_group": "本周已有任务", "status": "80%", "description": "已填本周进展",
    }).json()
    added = mutate(alice, "POST", f"{current_path}/tasks", existing["revision"])
    assert added.status_code == 201
    latest = added.json()
    resumed = mutate(alice, "POST", f"{current_path}/add-in-progress", latest["revision"]).json()
    assert resumed["tasks"][:2] == latest["tasks"]
    detail = resumed["tasks"][2]
    assert (detail["status"], detail["description"]) == ("40%", "")
    assert detail["has_history"] and detail["board_task_id"] == original["board_task_id"]
    repeated = mutate(alice, "POST", f"{current_path}/add-in-progress", resumed["revision"]).json()
    assert repeated == {**resumed, "no_source": True}
    path = f"{current_path}/tasks/{detail['id']}"
    assert mutate(alice, "PATCH", path, resumed["revision"], {"task_group": "禁止改名"}).status_code == 409
    assert mutate(alice, "DELETE", path, resumed["revision"]).status_code == 409
    assert mutate(alice, "POST", f"{path}/transfer", resumed["revision"], {"user_id": 3}).status_code == 409
    revision = alice.get(week).json()["revision"]
    assert admin.delete(f"{week}/tasks/{original['id']}?revision={revision}&user_id=2").status_code == 409
    edited = mutate(alice, "PATCH", path, resumed["revision"], {
        "task_group": "跨周任务", "description": "本周进展", "status": "60%",
    }).json()
    assert edited["tasks"][2]["description"] == "本周进展"
    assert next(item for item in alice.get(board).json()["tasks"] if item["id"] == original["board_task_id"])["status"] == "60%"
    copied = mutate(alice, "POST", f"{path}/duplicate", edited["revision"]).json()
    duplicate = copied["tasks"][-1]
    assert not duplicate["has_history"] and duplicate["board_task_id"] != original["board_task_id"]
    assert alice.get(week).json()["tasks"][0]["status"] == "40%"


@pytest.mark.parametrize("resume_by_copy", [True, False])
def test_rollover_keeps_history_and_deduplicates_continuation(monkeypatch, resume_by_copy):
    alice = client("alice")
    board = "/api/board-tasks"
    previous = current_week()
    current = previous + timedelta(days=7)
    fields = {"name": "跨周任务", "category_name": "其他", "priority": "低"}
    card = alice.post(board, json=fields).json()
    card_path = f"{board}/{card['id']}"
    body = {"state": "in_progress", "revision": card["revision"], "week_start": str(previous)}
    assert alice.patch(f"{card_path}/status", json=body).status_code == 200
    old_path = f"/api/weeks/{previous}"
    old = alice.get(old_path).json()
    detail_id = old["tasks"][0]["id"]
    old = mutate(alice, "PATCH", f"{old_path}/tasks/{detail_id}", old["revision"], {"status": "40%"}).json()
    monkeypatch.setattr("app.main.current_work_week", lambda: current)
    current_path = f"/api/weeks/{current}"
    card, = alice.get(board).json()["tasks"]
    assert card["has_other_details"] and not card["has_current_detail"]
    query = f"?revision={card['revision']}&week_start={current}"
    assert alice.patch(card_path + query, json=fields).status_code == 409
    assert alice.delete(card_path + query).status_code == 409
    assert alice.post(card_path + "/duplicate" + query).status_code == 409
    if resume_by_copy:
        assert mutate(alice, "POST", f"{current_path}/carry-over", 0, {"mode": "append"}).status_code == 200
    else:
        body.update(revision=card["revision"], week_start=str(current))
        assert alice.patch(f"{card_path}/status", json=body).status_code == 200
    week = alice.get(current_path).json()
    detail, = week["tasks"]
    assert detail["status"] == "40%" and detail["board_task_id"] == card["id"]
    repeated = mutate(alice, "POST", f"{current_path}/carry-over", week["revision"], {"mode": "append"})
    assert repeated.json()["no_source"] and repeated.json()["tasks"] == week["tasks"]
    card, = alice.get(board).json()["tasks"]
    body.update(state="inbox", revision=card["revision"], week_start=str(current))
    assert alice.patch(f"{card_path}/status", json=body).status_code == 200
    assert alice.get(current_path).json()["tasks"] == []
    old["tasks"][0]["has_history"] = True
    assert alice.get(old_path).json() == old


def test_work_week_changes_at_shanghai_midnight(monkeypatch):
    from app.main import current_work_week

    class Clock:
        instant = datetime(2026, 11, 22, 15, 59, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, zone):
            return cls.instant.astimezone(zone)

    monkeypatch.setattr("app.main.datetime", Clock)
    assert current_work_week().isoformat() == "2026-11-16"
    Clock.instant += timedelta(seconds=1)
    assert current_work_week().isoformat() == "2026-11-23"


def test_concurrent_move_creates_only_one_detail():
    first, second = client("alice"), client("alice")
    card = first.post("/api/board-tasks", json={"name": "并发测试", "category_name": "其他", "priority": "低"}).json()
    path = f"/api/board-tasks/{card['id']}/status"
    week = current_week()
    body = {"state": "in_progress", "revision": card["revision"], "week_start": str(week)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda session: session.patch(path, json=body).status_code, [first, second]))
    assert sorted(codes) == [200, 409]
    detail, = first.get(f"/api/weeks/{week}").json()["tasks"]
    assert detail["board_task_id"] == card["id"]


def test_board_order_persists_and_cross_column_moves_insert_at_top():
    alice = client("alice")
    board = "/api/board-tasks"
    week_start = str(current_week())
    first, second, third = (alice.post(board, json={"name": name, "category_name": "其他", "priority": "低"}).json()
                            for name in ("第一条", "第二条", "第三条"))
    url = f"{board}/{third['id']}/position"
    body = {"before_id": first["id"], "revision": third["revision"], "week_start": week_start}
    assert alice.patch(url, json=body).status_code == 200
    assert alice.patch(url, json=body).status_code == 409

    def order(state):
        return [card["id"] for card in alice.get(board).json()["tasks"] if card["state"] == state]

    assert order("inbox") == [third["id"], first["id"], second["id"]]
    for card in (first, second):
        response = alice.patch(f"{board}/{card['id']}/status", json={
            "state": "in_progress", "revision": card["revision"], "week_start": week_start,
        })
        assert response.status_code == 200, response.text
    assert order("in_progress") == [second["id"], first["id"]]
    assert alice.patch(url, json={**body, "revision": third["revision"] + 1}).status_code == 409
    assert order("inbox") == [third["id"]]
    returned = alice.patch(f"{board}/{first['id']}/status", json={
        "state": "inbox", "revision": first["revision"] + 1, "week_start": week_start,
    })
    assert returned.status_code == 200, returned.text
    assert order("inbox") == [first["id"], third["id"]]


def test_copy_edit_and_delete_card_keep_independent_details():
    alice = client("alice")
    board_path = "/api/board-tasks"
    fields = {"name": "看板名称", "category_name": "其他", "priority": "低"}
    card = alice.post(board_path, json=fields).json()
    card_path = f"{board_path}/{card['id']}"
    week = current_week()
    query = f"?revision=0&week_start={week}"
    copied = alice.post(card_path + "/duplicate" + query).json()
    assert copied["id"] != card["id"] and copied["name"] == card["name"] and copied["state"] == "inbox"
    card = alice.patch(f"{card_path}/status", json={"state": "in_progress", "revision": 0, "week_start": str(week)}).json()
    week_path = f"/api/weeks/{week}"
    detail, = (data := alice.get(week_path).json())["tasks"]
    edited = mutate(alice, "PATCH", f"{week_path}/tasks/{detail['id']}", data["revision"], {"task_group": "周报别名"}).json()
    card, = (item for item in alice.get(board_path).json()["tasks"] if item["id"] != copied["id"])
    response = alice.patch(f"{card_path}?revision={card['revision']}&week_start={week}", json={**fields, "name": "周报别名", "priority": "高"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "周报别名"
    detail, = (data := alice.get(week_path).json())["tasks"]
    assert data["revision"] > edited["revision"] and detail["task_group"] == "周报别名" and detail["priority"] == "高"
    assert alice.delete(f"{card_path}?revision={response.json()['revision']}&week_start={week}").status_code == 200
    assert alice.get(week_path).json()["tasks"] == []
    assert [item["id"] for item in alice.get(board_path).json()["tasks"]] == [copied["id"]]
