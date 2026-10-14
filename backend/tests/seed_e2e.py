"""Reset only the dedicated local E2E database, then create test accounts."""
import os
from app.db import Base, SessionLocal, engine
from app.main import hasher
from app.models import User

if "127.0.0.1:15433" not in os.environ.get("DATABASE_URL", ""):
    raise SystemExit("Refusing to seed a non-test database")

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with SessionLocal() as db:
    for username, name, role in [("admin", "管理员", "admin"), ("alice", "小王", "user"), ("bob", "小李", "user")]:
        db.add(User(username=username, display_name=name, role=role, password_hash=hasher.hash("e2e-password-123")))
    db.commit()
print("Dedicated E2E database ready")
