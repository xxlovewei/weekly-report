import getpass
from sqlalchemy import select
from pwdlib import PasswordHash
from .db import SessionLocal
from .models import User

def main():
    username = input("管理员用户名：").strip().lower()
    display_name = input("显示姓名：").strip()
    password = getpass.getpass("密码（至少 6 位）：")
    if not username or not display_name or len(password) < 6:
        raise SystemExit("用户名、显示姓名和至少 6 位密码均为必填项")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.username == username)):
            raise SystemExit("用户名已存在")
        db.add(User(username=username, display_name=display_name, password_hash=PasswordHash.recommended().hash(password), role="admin"))
        db.commit()
    print("管理员创建成功")

if __name__ == "__main__":
    main()

