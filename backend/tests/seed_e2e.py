"""Reset only the dedicated local E2E database, then create test accounts."""
import os
import argparse
from datetime import timedelta
from app.db import Base, SessionLocal, engine
from app.main import current_work_week, hasher
from app.models import Task, User, Week

if "127.0.0.1:15433" not in os.environ.get("DATABASE_URL", ""):
    raise SystemExit("Refusing to seed a non-test database")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--keep-schema", action="store_true", help="Seed a newly migrated empty database without removing triggers")
if not parser.parse_args().keep_schema:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
with SessionLocal() as db:
    for username, name, role in [("admin", "管理员", "admin"), ("alice", "小王", "user"), ("bob", "小李", "user")]:
        account = User(username=username, display_name=name, roles=[role], password_hash=hasher.hash("e2e-password-123"))
        db.add(account)
        if username == "alice":
            # 普通用户无法写上周，提前为跨周复制场景准备一条历史明细。
            db.flush()
            previous = Week(user_id=account.id, start_date=current_work_week() - timedelta(days=7))
            previous.tasks.append(Task(position=1, description="上周遗留工作"))
            db.add(previous)
    db.commit()
print("Dedicated E2E database ready")
