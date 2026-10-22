import os
test_database_url = os.environ.get("TEST_DATABASE_URL", "")
if "127.0.0.1:15433" not in test_database_url:
    raise RuntimeError("Set TEST_DATABASE_URL to the dedicated local test database on port 15433")
os.environ["DATABASE_URL"] = test_database_url
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import Base, SessionLocal, engine
from app.main import app, hasher
from app.models import User

PASSWORD = "correct-horse-123"

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([
            User(username="admin", display_name="管理员", role="admin", password_hash=hasher.hash(PASSWORD)),
            User(username="alice", display_name="小王", role="user", password_hash=hasher.hash(PASSWORD)),
            User(username="bob", display_name="小李", role="user", password_hash=hasher.hash(PASSWORD)),
        ])
        db.commit()
    yield

def client(username):
    c = TestClient(app)
    result = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert result.status_code == 200, result.text
    c.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return c

def mutate(c, method, path, revision, body=None, key=None):
    headers = {"Idempotency-Key": key} if key else None
    return c.request(method, f"{path}?revision={revision}", json=body, headers=headers)

def test_auth_roles_sessions_and_history():
    with TestClient(app) as anon:
        assert anon.get("/api/users").status_code == 401
        wrong = anon.post("/api/auth/login", json={"username":"admin","password":"wrong"})
        assert wrong.status_code == 401 and wrong.json()["detail"] == "用户名或密码错误"
    alice = client("alice")
    admin = client("admin")
    assert alice.get("/api/users").status_code == 403
    assert alice.post("/api/categories", json={"name":"开发"}, headers={"X-CSRF-Token":"wrong"}).status_code == 403
    assert alice.post("/api/categories", json={"name":"开发"}).status_code == 201
    assert mutate(alice, "POST", "/api/weeks/2026-10-12/tasks", 0).status_code == 201
    users = admin.get("/api/users").json()
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    assert admin.patch(f"/api/users/{admin_id}", json={"role":"user"}).status_code == 403
    assert admin.delete(f"/api/users/{admin_id}").status_code == 403
    assert admin.delete(f"/api/users/{alice_id}").status_code == 200
    assert all(u["id"] != alice_id for u in admin.get("/api/users").json())
    assert alice.get("/api/auth/me").status_code == 401
    assert admin.get("/api/reports/2026-10-12/users/2").json()["tasks"]
    assert any(u["is_deleted"] and u["id"] == alice_id for u in admin.get("/api/reports/2026-10-12").json())
    with SessionLocal() as db:
        deleted = db.get(User, alice_id)
        assert deleted is not None and deleted.is_deleted and deleted.is_active
    assert admin.patch(f"/api/users/{alice_id}", json={"is_active": True}).status_code == 404
    assert admin.post(f"/api/users/{alice_id}/password", json={"password": PASSWORD}).status_code == 404
    assert TestClient(app).post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 401
    assert admin.post("/api/users", json={"username": "next-admin", "display_name": "管理员", "password": PASSWORD, "role": "admin"}).status_code == 422

def test_categories_snapshot_ownership_and_reset():
    alice = client("alice")
    bob = client("bob")
    admin = client("admin")
    cat = alice.post("/api/categories", json={"name":"开发"}).json()
    assert bob.patch(f"/api/categories/{cat['id']}", json={"name":"偷改"}).status_code == 404
    result = mutate(alice, "POST", "/api/weeks/2026-10-12/tasks", 0).json()
    task_id = result["tasks"][0]["id"]
    result = mutate(alice, "PATCH", f"/api/weeks/2026-10-12/tasks/{task_id}", 1, {"category_name":"开发"}).json()
    assert alice.patch(f"/api/categories/{cat['id']}", json={"name":"产品"}).status_code == 200
    assert alice.delete(f"/api/categories/{cat['id']}").status_code == 200
    assert alice.get("/api/weeks/2026-10-12").json()["tasks"][0]["category_name"] == "开发"
    assert bob.get("/api/weeks/2026-10-12").json()["tasks"] == []
    assert admin.patch(f"/api/weeks/2026-10-12/tasks/{task_id}?revision=0", json={"notes":"x"}).status_code == 404
    alice_id = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "alice")
    assert admin.post(f"/api/users/{alice_id}/password", json={"password":"new-secret-123"}).status_code == 200
    assert alice.get("/api/auth/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username":"alice","password":PASSWORD}).status_code == 401

def test_task_order_copy_revision_and_idempotency():
    alice = client("alice")
    week = "/api/weeks/2026-10-05"
    first = mutate(alice, "POST", f"{week}/tasks", 0, key="first").json()
    assert mutate(alice, "POST", f"{week}/tasks", 0, key="first").json() == first
    first_id = first["tasks"][0]["id"]
    assert mutate(alice, "POST", f"{week}/tasks", 0).status_code == 409
    changed = mutate(alice, "PATCH", f"{week}/tasks/{first_id}", 1, {"description":"准备上线", "work_days":[1,3], "status":"90%"}).json()
    assert mutate(alice, "PATCH", f"{week}/tasks/{first_id}", 2, {"work_days":[1,1]}).status_code == 422
    assert mutate(alice, "PATCH", f"{week}/tasks/{first_id}", 2, {"status":"100%"}).status_code == 422
    duplicate = mutate(alice, "POST", f"{week}/tasks/{first_id}/duplicate", 2, key="dup").json()
    assert [t["position"] for t in duplicate["tasks"]] == [1,2]
    assert duplicate["tasks"][1]["work_days"] == [1,3]
    assert mutate(alice, "POST", f"{week}/tasks/{first_id}/duplicate", 2, key="dup").json() == duplicate
    target = "/api/weeks/2026-10-12"
    carried = mutate(alice, "POST", f"{target}/carry-over", 0, {"mode":"append"}, key="carry1").json()
    assert len(carried["tasks"]) == 2
    assert all(t["work_days"] == [] for t in carried["tasks"])
    assert mutate(alice, "POST", f"{target}/carry-over", 0, {"mode":"append"}, key="carry1").json() == carried
    overwritten = mutate(alice, "POST", f"{target}/carry-over", 1, {"mode":"overwrite"}).json()
    assert len(overwritten["tasks"]) == 2
    removed = mutate(alice, "DELETE", f"{target}/tasks/{overwritten['tasks'][0]['id']}", 2).json()
    assert [t["position"] for t in removed["tasks"]] == [1]

def test_no_source_does_not_clear_and_blank_status_copies():
    alice = client("alice")
    target = "/api/weeks/2026-10-12"
    created = mutate(alice, "POST", f"{target}/tasks", 0).json()
    untouched = mutate(alice, "POST", f"{target}/carry-over", 1, {"mode":"overwrite"}).json()
    assert untouched["no_source"] is True and untouched["tasks"] == created["tasks"]
    source = mutate(alice, "POST", "/api/weeks/2026-10-05/tasks", 0).json()
    assert source["tasks"][0]["status"] is None
    copied = mutate(alice, "POST", f"{target}/carry-over", 1, {"mode":"append"}).json()
    assert len(copied["tasks"]) == 2
    assert copied["tasks"][1]["status"] is None

def test_reorder_tasks_persists_and_rejects_invalid_or_stale_orders():
    alice, bob = client("alice"), client("bob")
    week = "/api/weeks/2026-10-12"
    for revision in range(3):
        original = mutate(alice, "POST", f"{week}/tasks", revision).json()
    ids = [task["id"] for task in original["tasks"]]
    foreign = mutate(bob, "POST", f"{week}/tasks", 0).json()["tasks"][0]["id"]
    other_week = mutate(alice, "POST", "/api/weeks/2026-10-19/tasks", 0).json()["tasks"][0]["id"]
    endpoint = f"{week}/tasks/order"
    for invalid in [[], ids[:-1], [ids[0], ids[0], ids[2]], [*ids, foreign], [ids[0], ids[1], foreign], [ids[0], ids[1], other_week]]:
        assert mutate(alice, "PUT", endpoint, 3, {"task_ids": invalid}).status_code == 422
        assert alice.get(week).json() == original

    desired = [ids[2], ids[0], ids[1]]
    response = mutate(alice, "PUT", endpoint, 3, {"task_ids": desired})
    assert response.status_code == 200, response.text
    reordered = response.json()
    assert reordered["revision"] == 4
    assert [task["id"] for task in reordered["tasks"]] == desired
    assert [task["position"] for task in reordered["tasks"]] == [1, 2, 3]
    assert alice.get(week).json() == reordered
    assert client("admin").get(f"/api/reports/2026-10-12/users/2").json() == reordered
    assert mutate(alice, "PUT", endpoint, 3, {"task_ids": ids}).status_code == 409
    assert alice.get(week).json() == reordered
    assert mutate(bob, "PUT", endpoint, 1, {"task_ids": desired}).status_code == 422
    assert bob.get(week).json()["tasks"][0]["id"] == foreign
    assert alice.put(f"{endpoint}?revision=4", json={"task_ids": ids}, headers={"X-CSRF-Token": "wrong"}).status_code == 403

def test_all_statuses_user_edit_and_password_change():
    alice = client("alice")
    admin = client("admin")
    alice_id = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "alice")
    assert admin.patch(f"/api/users/{alice_id}", json={"username":"alice.renamed", "display_name":"新姓名"}).status_code == 200
    assert admin.patch(f"/api/users/{alice_id}", json={"username":"admin"}).status_code == 409
    current = mutate(alice, "POST", "/api/weeks/2026-10-12/tasks", 0).json()
    task_id = current["tasks"][0]["id"]
    for status in ["已完成", "90%", "80%", "70%", "60%", "50%", "40%", "30%", "20%", "10%", "5%", None]:
        current = mutate(alice, "PATCH", f"/api/weeks/2026-10-12/tasks/{task_id}", current["revision"], {"status": status}).json()
        assert current["tasks"][0]["status"] == status
    assert alice.post("/api/auth/password", json={"old_password":PASSWORD, "new_password":"another-secret-123"}).status_code == 200
    assert alice.get("/api/auth/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username":"alice.renamed", "password":"another-secret-123"}).status_code == 200

def test_new_user_password_gate_and_six_character_limit():
    manager = client("admin")
    assert manager.post("/api/users", json={"username":"new","display_name":"新人","password":"12345"}).status_code == 422
    created = manager.post("/api/users", json={"username":"new","display_name":"新人","password":"123456"})
    assert created.status_code == 201 and created.json()["must_change_password"] is True
    new = client_with_password("new", "123456")
    assert new.get("/api/weeks/2026-10-12").status_code == 403
    assert new.get("/api/auth/me").json()["user"]["must_change_password"] is True
    reused = new.post("/api/auth/password", json={"old_password":"123456","new_password":"123456"})
    assert reused.status_code == 400 and reused.json()["detail"] == "新密码不能与当前密码相同"
    assert new.post("/api/auth/password", json={"old_password":"123456","new_password":"654321"}).status_code == 200
    assert new.get("/api/auth/me").status_code == 401
    assert client_with_password("new", "654321").get("/api/weeks/2026-10-12").status_code == 200
    assert manager.post(f"/api/users/{created.json()['id']}/password", json={"password":"abcdef"}).status_code == 200
    assert client_with_password("new", "abcdef").get("/api/weeks/2026-10-12").status_code == 403

def client_with_password(username, password):
    c = TestClient(app)
    response = c.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    c.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return c

def test_report_admin_hidden_and_calendar_marks_task_group():
    manager, alice = client("admin"), client("alice")
    week = "/api/weeks/2026-10-12"
    admin_task = mutate(manager, "POST", f"{week}/tasks", 0).json()
    alice_task = mutate(alice, "POST", f"{week}/tasks", 0).json()
    alice_id = next(u["id"] for u in manager.get("/api/users").json() if u["username"] == "alice")
    admin_id = next(u["id"] for u in manager.get("/api/users").json() if u["username"] == "admin")
    assert all(u["id"] != admin_id for u in alice.get("/api/reports/2026-10-12").json())
    assert alice.get(f"/api/reports/2026-10-12/users/{admin_id}").status_code == 404
    assert alice.get("/api/calendar/marks?year=2026&month=10&scope=reports").json() == ["2026-10-12"]
    assert manager.get("/api/calendar/marks?year=2026&month=10&scope=work").json() == ["2026-10-12"]
    assert alice.get("/api/calendar/marks?year=2026&month=11&scope=work").json() == []
    assert mutate(manager, "POST", "/api/weeks/2026-10-19/tasks", 0).status_code == 201
    assert alice.get("/api/calendar/marks?year=2026&month=10&scope=reports").json() == ["2026-10-12"]
    assert manager.get("/api/calendar/marks?year=2026&month=10&scope=work").json() == ["2026-10-12", "2026-10-19"]
    task_id = alice_task["tasks"][0]["id"]
    changed = mutate(alice, "PATCH", f"{week}/tasks/{task_id}", 1, {"category_name":"开发相关", "task_group":"平台升级"}).json()
    assert changed["tasks"][0]["task_group"] == "平台升级"
    duplicated = mutate(alice, "POST", f"{week}/tasks/{task_id}/duplicate", 2).json()
    assert duplicated["tasks"][1]["task_group"] == "平台升级"
    carried = mutate(alice, "POST", "/api/weeks/2026-10-19/carry-over", 0, {"mode":"append"}).json()
    assert carried["tasks"][0]["task_group"] == "平台升级"
    assert alice.get(f"/api/reports/2026-10-12/users/{alice_id}").json()["tasks"][0]["category_name"] == "开发相关"

def test_meeting_crud_shared_access_and_filter():
    alice, bob = client("alice"), client("bob")
    payload = {"meeting_date":"2026-10-13", "meeting_type":"例会", "content":"项目同步", "needs_follow_up":True,
               "tasks":[{"name":"联调", "status":"未完成"}, {"name":"验收", "status":None}]}
    created = alice.post("/api/meetings", json=payload)
    assert created.status_code == 201, created.text
    assert alice.post("/api/meetings", json={**payload, "needs_follow_up":False}).status_code == 422
    meeting_id = created.json()["id"]
    assert [t["position"] for t in created.json()["tasks"]] == [1, 2]
    assert bob.get(f"/api/meetings/{meeting_id}").status_code == 200
    assert bob.get("/api/meetings?status=未完成").json()["total"] == 1
    assert bob.get("/api/meetings?status=已完成").json()["total"] == 0
    assert bob.get("/api/meetings?status=未选择").json()["total"] == 1
    assert bob.get("/api/meetings?content=同步&date_from=2026-10-13&date_to=2026-10-13").json()["total"] == 1
    assert bob.get("/api/meetings?date_from=2026-10-14").json()["total"] == 0
    newer = {**payload, "meeting_date":"2026-10-14", "tasks":[]}
    assert bob.post("/api/meetings", json=newer).status_code == 201
    listed = alice.get("/api/meetings?page=1&page_size=1").json()
    assert listed["total"] == 2 and listed["items"][0]["meeting_date"] == "2026-10-14"
    assert bob.put(f"/api/meetings/{meeting_id}", json={**payload, "needs_follow_up":False, "tasks":[]}).json()["tasks"] == []
    assert alice.delete(f"/api/meetings/{meeting_id}").status_code == 200
    assert bob.get(f"/api/meetings/{meeting_id}").status_code == 404


def test_meeting_creator_and_unique_updaters():
    alice, bob = client("alice"), client("bob")
    payload = {"meeting_date": "2026-10-14", "meeting_type": "例会", "content": "人员记录"}
    created = alice.post("/api/meetings", json=payload).json()
    assert created["creator"]["username"] == "alice"
    assert created["updaters"] == []
    path = f"/api/meetings/{created['id']}"
    assert bob.put(path, json={**payload, "creator_id": 3}).status_code == 422
    for editor in (bob, alice, bob):
        updated = editor.put(path, json=payload)
        assert updated.status_code == 200, updated.text
    for result in (alice.get(path).json(), bob.get("/api/meetings").json()["items"][0]):
        assert result["creator"]["username"] == "alice"
        assert [u["username"] for u in result["updaters"]] == ["alice", "bob"]
    # Records predating attribution must remain readable and editable.
    from app.models import Meeting
    with SessionLocal() as db:
        legacy = Meeting(meeting_date=date(2026, 10, 13), meeting_type="历史", content="旧记录")
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
    legacy_path = f"/api/meetings/{legacy_id}"
    assert alice.get(legacy_path).json()["creator"] is None
    result = bob.put(legacy_path, json=payload).json()
    assert result["creator"] is None
    assert [u["username"] for u in result["updaters"]] == ["bob"]
    assert alice.delete(path).status_code == 200
