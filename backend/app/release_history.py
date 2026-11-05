"""启动时将随版本发布的说明写入发版记录，同版本只记录一次。"""
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from .db import SessionLocal
from .models import ReleaseRecord


def main():
    releases = json.loads((Path(__file__).resolve().parent.parent / "releases.json").read_text(encoding="utf-8"))
    if not isinstance(releases, dict) or not releases:
        raise SystemExit("版本说明不能为空")
    with SessionLocal() as db:
        for version, description in releases.items():
            if not isinstance(version, str) or not 1 <= len(version) <= 40 or not isinstance(description, str) or not description.strip():
                raise SystemExit("版本号或更新说明无效")
            existing = db.scalar(select(ReleaseRecord).where(ReleaseRecord.version == version))
            if existing and existing.description != description.strip():
                raise SystemExit(f"版本 {version} 已有不同的更新说明，请使用新版本号")
            # 唯一约束保证多个 API 实例启动时不会重复写入。
            db.execute(insert(ReleaseRecord).values(version=version, description=description.strip()).on_conflict_do_nothing(index_elements=["version"]))
        db.commit()
    print("发版记录已同步")


if __name__ == "__main__":
    main()
