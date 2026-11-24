from datetime import date, timedelta

from .test_api import client, clean_db, mutate


def test_next_week_plans_expire_and_leave_an_independent_work_detail(monkeypatch):
    current = date(2026, 11, 23)
    following = current + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: current)
    alice, bob, admin = client("alice"), client("bob"), client("admin")
    week = f"/api/weeks/{following}"
    plans = f"{week}/plans"
    assert mutate(alice, "POST", f"/api/weeks/{following + timedelta(days=7)}/plans", 0).status_code == 403
    assert mutate(admin, "POST", f"{week}/tasks", 0).status_code == 403
    added = mutate(alice, "POST", plans, 0, key="plan").json()
    assert added["tasks"] == []
    assert mutate(alice, "POST", plans, 0, key="plan").json() == added
    plan, = added["plans"]
    path = f"{plans}/{plan['id']}"
    assert mutate(bob, "PATCH", path, 0, {"task_group": "误修改"}).status_code == 404
    extras = mutate(alice, "POST", plans, added["revision"]).json()
    new_plan, original_plan = extras["plans"]
    assert new_plan["position"] == 1 and original_plan["id"] == plan["id"]
    removed = mutate(alice, "DELETE", f"{plans}/{new_plan['id']}", extras["revision"]).json()
    edited = mutate(alice, "PATCH", path, removed["revision"], {
        "task_group": "下周联调\n确认发布计划", "description": "先核对清单", "work_days": [1, 3],
        "status": "已完成", "category_name": "联调联试", "priority": "高",
    }).json()
    assert alice.get(week).json() == edited
    assert alice.get(f"/api/reports/{following}/users/2").json()["tasks"] == []
    assert str(following) in alice.get("/api/calendar/marks", params={"year": 2026, "month": 11, "scope": "work"}).json()

    current = following
    assert mutate(alice, "PATCH", path, edited["revision"], {"task_group": "到期后写入"}).status_code == 403
    assert admin.delete(f"{path}?user_id=2&revision={edited['revision']}").status_code == 403
    assert alice.delete(f"{path}?revision={edited['revision']}").status_code == 403
    assert mutate(alice, "POST", plans, 0, key="plan").status_code == 403
    applied = alice.get(week).json()
    assert applied["plans"] == edited["plans"]
    detail, = applied["tasks"]
    assert detail["task_group"] == "下周联调\n确认发布计划" and detail["work_days"] == [1, 3]
    assert (detail["status"], detail["description"]) == (None, "先核对清单")
    card = next(card for card in alice.get("/api/board-tasks").json()["tasks"] if card["id"] == detail["board_task_id"])
    assert (card["name"], card["category_name"], card["priority"], card["state"]) == (
        "下周联调\n确认发布计划", "联调联试", "高", "inbox")
    assert alice.get(week).json() == applied
    changed = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", applied["revision"], {"description": "联调已完成"}).json()
    assert changed["plans"] == edited["plans"]
    assert changed["tasks"][0]["description"] == "联调已完成"


def test_copy_in_progress_reuses_card_and_rolls_over_latest_actual_status(monkeypatch):
    current = date(2026, 11, 23)
    following = current + timedelta(days=7)
    monkeypatch.setattr("app.main.current_work_week", lambda: current)
    alice = client("alice")
    board = "/api/board-tasks"
    today, future = f"/api/weeks/{current}", f"/api/weeks/{following}"
    created = mutate(alice, "POST", f"{today}/tasks", 0).json()
    source, = created["tasks"]
    detail_path = f"{today}/tasks/{source['id']}"
    changed = mutate(alice, "PATCH", detail_path, created["revision"], {
        "task_group": "跨周联调", "status": "40%", "description": "本周联调", "notes": "核对接口\n跟进反馈",
    }).json()
    card, = alice.get(board).json()["tasks"]
    copy_path = f"{future}/plans/add-in-progress"
    copied = mutate(alice, "POST", copy_path, 0, key="continue").json()
    plan, = copied["plans"]
    assert (plan["task_group"], plan["status"], plan["description"]) == ("跨周联调", "40%", "")
    assert mutate(alice, "POST", f"{future}/plans/from-board/{card['id']}", copied["revision"]).json() == copied
    assert mutate(alice, "POST", copy_path, 0, key="continue").json() == copied
    assert mutate(alice, "POST", copy_path, copied["revision"]).json() == {**copied, "no_source": True}
    plan_path = f"{future}/plans/{plan['id']}"
    planned = mutate(alice, "PATCH", plan_path, copied["revision"], {"status": "已完成"}).json()
    assert alice.get(board).json()["tasks"] == [card]
    assert mutate(alice, "PATCH", plan_path, planned["revision"], {
        "priority": "高", "description": "继续联调\n跟进修复",
    }).status_code == 200
    assert alice.get(board).json()["tasks"][0]["priority"] == "高"
    latest = alice.get(today).json()
    assert latest["tasks"][0]["priority"] == "高"
    assert latest["revision"] > changed["revision"]
    assert mutate(alice, "PATCH", detail_path, latest["revision"], {"status": "70%"}).status_code == 200

    current = following
    active_card, = alice.get(board).json()["tasks"]
    assert active_card["has_current_detail"] and active_card["id"] == card["id"]
    week = alice.get(future).json()
    detail, = week["tasks"]
    assert (detail["status"], detail["description"], detail["notes"]) == ("70%", "继续联调\n跟进修复", "核对接口\n跟进反馈")
    assert alice.get(future).json() == week
    assert week["plans"][0]["status"] == "已完成"


def test_add_plan_from_board_reuses_owned_active_card_once(monkeypatch):
    current = date(2026, 11, 23)
    monkeypatch.setattr("app.main.current_work_week", lambda: current)
    alice, bob = client("alice"), client("bob")
    board = "/api/board-tasks"
    week = f"/api/weeks/{current + timedelta(days=7)}"
    card = alice.post(board, json={"name": "下周联调", "category_name": "联调联试", "priority": "高"}).json()
    path = f"{week}/plans/from-board/{card['id']}"
    assert mutate(bob, "POST", path, 0).status_code == 404
    assert mutate(alice, "POST", path, 1).status_code == 409
    response = mutate(alice, "POST", path, 0, key="from-board")
    assert response.status_code == 201
    added = response.json()
    plan, = added["plans"]
    assert (plan["board_task_id"], plan["task_group"], plan["category_name"], plan["priority"], plan["status"]) == (
        card["id"], "下周联调", "联调联试", "高", None)
    assert mutate(alice, "POST", path, 0, key="from-board").json() == added
    assert mutate(alice, "POST", path, added["revision"]).json() == added
    assert alice.get(board).json()["tasks"] == [card]
    assert alice.get(week).json() == added
    newest = alice.post(board, json={"name": "优先安排", "category_name": "联调联试", "priority": "中"}).json()
    latest = mutate(alice, "POST", f"{week}/plans/from-board/{newest['id']}", added["revision"]).json()
    assert [(row["board_task_id"], row["position"]) for row in latest["plans"]] == [(newest["id"], 1), (card["id"], 2)]
    assert mutate(alice, "POST", path, latest["revision"]).json() == latest
    assert alice.get(week).json() == latest
    completed = alice.patch(f"{board}/{card['id']}/status", json={
        "state": "done", "revision": card["revision"], "week_start": current.isoformat(),
    })
    assert completed.status_code == 200
    assert mutate(alice, "POST", path, latest["revision"]).status_code == 404
