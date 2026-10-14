from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from importlib import import_module

from tests.test_api import PASSWORD, clean_db, client
import app.main as main
from fastapi.testclient import TestClient
from app.db import SessionLocal
from app.models import User
from sqlalchemy import select
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db import engine


def attempt(username="alice", password="wrong-password"):
    return TestClient(main.app).post("/api/auth/login", json={"username": username, "password": password})


def test_admin_status_and_unlock():
    manager, alice = client("admin"), client("alice")
    users = manager.get("/api/users").json()
    assert all(user["status"] == "正常" for user in users)
    alice_id = next(user["id"] for user in users if user["username"] == "alice")
    admin_id = next(user["id"] for user in users if user["username"] == "admin")
    assert manager.patch(f"/api/users/{admin_id}", json={"status": "锁定"}).status_code == 409
    assert manager.patch(f"/api/users/{alice_id}", json={"status": "invalid"}).status_code == 422
    assert alice.patch(f"/api/users/{alice_id}", json={"status": "锁定"}).status_code == 403
    assert manager.patch(f"/api/users/{alice_id}", json={"status": "锁定"}).json()["status"] == "锁定"
    for password in (PASSWORD, "wrong-password"):
        result = attempt(password=password)
        assert result.status_code == 401
        assert result.json()["detail"] == "账号已锁定，请联系管理员。"
        assert "zhoubao_session" not in result.cookies
    assert alice.get("/api/auth/me").status_code == 401
    assert manager.patch(f"/api/users/{alice_id}", json={"status": "正常"}).status_code == 200
    assert attempt(password=PASSWORD).status_code == 200
    assert manager.post("/api/users", json={"username": "new", "display_name": "新人", "password": "123456"}).json()["status"] == "正常"


def test_six_failures_lock_and_unlock_clears_history():
    manager, alice = client("admin"), client("alice")
    for _ in range(5):
        assert attempt(username="ALICE").json()["detail"] == "用户名或密码错误"
    # Successful login does not remove failures still inside the rolling window.
    assert attempt(password=PASSWORD).status_code == 200
    assert attempt().json()["detail"] == "账号已锁定，请联系管理员。"
    assert attempt(password=PASSWORD).status_code == 401
    assert attempt(username="bob", password=PASSWORD).status_code == 200
    assert alice.get("/api/auth/me").status_code == 401
    user = next(user for user in manager.get("/api/users").json() if user["username"] == "alice")
    assert user["status"] == "锁定"
    assert manager.patch(f"/api/users/{user['id']}", json={"status": "正常"}).status_code == 200
    assert attempt().json()["detail"] == "用户名或密码错误"
    assert attempt(password=PASSWORD).status_code == 200


def test_rolling_window(monkeypatch):
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(main, "datetime", Clock)
    assert attempt().status_code == 401
    now += timedelta(seconds=100)
    for _ in range(4):
        assert attempt().json()["detail"] == "用户名或密码错误"
    now += timedelta(seconds=200)
    assert attempt().json()["detail"] == "用户名或密码错误"
    assert attempt().json()["detail"] == "账号已锁定，请联系管理员。"
    now += timedelta(minutes=6)
    assert attempt(password=PASSWORD).json()["detail"] == "账号已锁定，请联系管理员。"


def test_concurrent_failures_are_counted():
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: attempt(), range(6)))
    assert sum(result.json()["detail"] == "账号已锁定，请联系管理员。" for result in results) == 1
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == "alice")).status == "锁定"


def test_unknown_user_is_not_counted():
    for _ in range(7):
        assert attempt(username="unknown").json()["detail"] == "用户名或密码错误"
    assert attempt(password=PASSWORD).status_code == 200


def test_saving_normal_user_does_not_clear_failures():
    manager = client("admin")
    for _ in range(5):
        assert attempt().status_code == 401
    alice_id = next(user["id"] for user in manager.get("/api/users").json() if user["username"] == "alice")
    assert manager.patch(f"/api/users/{alice_id}", json={"status": "正常", "display_name": "新姓名"}).status_code == 200
    assert attempt().json()["detail"] == "账号已锁定，请联系管理员。"


def test_migration_backfills_existing_users_and_handles_fresh_schema(monkeypatch):
    migration = import_module("migrations.versions.0004_account_lock")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
    with SessionLocal() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 3
        assert all(user.status == "正常" and user.failed_login_times == [] for user in users)
