from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from datetime import date

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from .credentials import credential_post
from .test_api import PASSWORD, client, clean_db, engine, mutate


def test_dual_role_applies_to_permissions_and_workflows(monkeypatch):
    monkeypatch.setattr("app.main.current_work_week", lambda: date(2026, 10, 12))
    admin, alice, bob = client("admin"), client("alice"), client("bob")
    alice_id = alice.get("/api/auth/me").json()["user"]["id"]
    path = f"/api/users/{alice_id}"
    for roles in ([], ["unknown"], None):
        assert admin.patch(path, json={"roles": roles}).status_code == 422

    updated = admin.patch(path, json={"roles": ["user", "admin", "user"]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["roles"] == ["admin", "user"]
    assert alice.get("/api/auth/me").status_code == 401

    alice = client("alice")
    assert alice.get("/api/auth/me").json()["user"]["roles"] == ["admin", "user"]
    assert alice.get("/api/users").status_code == 200
    assert alice.get("/api/notifications?all_users=true").status_code == 200
    assert alice.get("/api/reviews/projects").status_code == 200
    assert admin.delete(path).status_code == 403

    week = "2026-10-12"
    source = mutate(bob, "POST", f"/api/weeks/{week}/tasks", 0).json()
    task_id = source["tasks"][0]["id"]
    assert [item["username"] for item in bob.get("/api/task-transfer-recipients").json()] == ["alice"]
    assert mutate(bob, "POST", f"/api/weeks/{week}/tasks/{task_id}/transfer", 1, {"user_id": alice_id}).status_code == 200
    assert {item["id"] for item in bob.get(f"/api/reports/{week}").json()} >= {alice_id}
    assert bob.get(f"/api/reports/{week}/users/{alice_id}").json()["tasks"][0]["id"] == task_id
    assert bob.get("/api/calendar/marks?year=2026&month=10&scope=reports").json() == [week]

    assert {item["username"] for item in bob.get("/api/meeting-assignees").json()} == {"alice", "bob"}
    meeting = bob.post("/api/meetings", json={
        "meeting_date": week, "meeting_type": "周会", "content": "双角色指派", "needs_follow_up": True,
        "tasks": [{"name": "跟进任务", "assignments": [{"user_id": alice_id}]}],
    })
    assert meeting.status_code == 201, meeting.text
    assert meeting.json()["tasks"][0]["assignments"][0]["user_id"] == alice_id

    # 排序、重复勾选和旧客户端重复提交同一角色都不改变角色集合。
    for payload in ({"roles": ["user", "admin"]}, {"role": "admin"}):
        assert admin.patch(path, json=payload).json()["roles"] == ["admin", "user"]
    assert alice.get("/api/auth/me").status_code == 200


def test_create_and_remove_admin_role_before_deletion():
    admin = client("admin")
    payload = {"username": "new", "display_name": "新用户", "password": PASSWORD}
    assert credential_post(admin, "/api/users", {**payload, "roles": []}).status_code == 422
    created = credential_post(admin, "/api/users", {**payload, "roles": ["user", "admin"]})
    assert created.status_code == 201, created.text
    assert created.json()["roles"] == ["admin", "user"]
    assert created.json()["must_change_password"]

    new = client("new")
    assert new.get("/api/users").status_code == 403
    path = f"/api/users/{created.json()['id']}"
    assert admin.delete(path).status_code == 403
    assert admin.patch(path, json={"roles": ["user"]}).json()["roles"] == ["user"]
    assert new.get("/api/auth/me").status_code == 401
    assert admin.delete(path).status_code == 200


def test_concurrent_edits_keep_one_effective_admin():
    admin, alice = client("admin"), client("alice")
    alice_id = alice.get("/api/auth/me").json()["user"]["id"]
    admin_id = admin.get("/api/auth/me").json()["user"]["id"]
    assert admin.patch(f"/api/users/{alice_id}", json={"roles": ["admin", "user"]}).status_code == 200
    alice = client("alice")

    # 两位管理员同时移除自己的管理员角色，只能有一个成功。
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            pool.submit(account.patch, f"/api/users/{user_id}", json={"roles": ["user"]})
            for account, user_id in ((admin, admin_id), (alice, alice_id))
        ]
        assert sorted(result.result().status_code for result in outcomes) == [200, 409]


def test_roles_migration_preserves_existing_assignments(monkeypatch):
    migration = import_module("migrations.versions.0013_user_roles")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.downgrade()
        assert dict(connection.execute(text("SELECT username, role FROM users")).tuples().all()) == {
            "admin": "admin", "alice": "user", "bob": "user",
        }
        migration.upgrade()
        assert dict(connection.execute(text("SELECT username, roles FROM users")).tuples().all()) == {
            "admin": ["admin"], "alice": ["user"], "bob": ["user"],
        }
