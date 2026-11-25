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
    removed = mutate(alice, "DELETE", f"{plans}/{extras['plans'][-1]['id']}", extras["revision"]).json()
    edited = mutate(alice, "PATCH", path, removed["revision"], {
        "task_group": "下周联调\n确认发布计划", "description": "先核对清单", "work_days": [1, 3],
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
    assert alice.get(week).json() == applied
    changed = mutate(alice, "PATCH", f"{week}/tasks/{detail['id']}", applied["revision"], {"description": "联调已完成"}).json()
    assert changed["plans"] == edited["plans"]
    assert changed["tasks"][0]["description"] == "联调已完成"
