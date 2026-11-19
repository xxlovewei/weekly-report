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


def test_board_move_and_week_status_sync():
    alice, bob = client("alice"), client("bob")
    board = "/api/board-tasks"
    week = f"/api/weeks/{current_week()}"
    created = alice.post(board, json={"name": "联调接口", "category_name": "联调联试", "priority": "高"})
    assert created.status_code == 201, created.text
    card = created.json()
    path = f"{board}/{card['id']}/status"
    body = {"state": "done", "revision": card["revision"], "week_start": str(current_week())}
    assert bob.patch(path, json=body).status_code == 404
    assert alice.patch(path, json=body).status_code == 200
    assert alice.patch(path, json=body).status_code == 409
    detail, = (data := alice.get(week).json())["tasks"]
    assert (detail["task_group"], detail["status"], detail["board_task_id"]) == ("联调接口", "已完成", card["id"])
    updated = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", data["revision"], {"status": None})
    assert updated.status_code == 200
    card, = alice.get(board).json()["tasks"]
    assert card["state"] == "inbox" and card["has_current_detail"]
    body.update(state="in_progress", revision=card["revision"])
    assert alice.patch(path, json=body).status_code == 200
    detail, = alice.get(week).json()["tasks"]
    assert detail["status"] == "5%"


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
    response = alice.patch(f"{card_path}?revision={card['revision']}&week_start={week}", json={**fields, "priority": "高"})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == fields["name"]
    detail, = (data := alice.get(week_path).json())["tasks"]
    assert data["revision"] > edited["revision"] and detail["task_group"] == "周报别名" and detail["priority"] == "高"
    assert alice.delete(f"{card_path}?revision={response.json()['revision']}&week_start={week}").status_code == 200
    assert alice.get(week_path).json()["tasks"] == []
    assert [item["id"] for item in alice.get(board_path).json()["tasks"]] == [copied["id"]]
