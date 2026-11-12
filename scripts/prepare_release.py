"""统一准备生产版本号、镜像标签及更新说明，实际部署另行执行。"""
import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description="准备生产版本和发版说明")
    parser.add_argument("version", help="例如 1.2.6")
    parser.add_argument("--notes-file", required=True, type=Path, help="UTF-8 更新说明文件")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("版本号必须采用 1.2.6 格式")
    description = args.notes_file.read_text(encoding="utf-8-sig").strip()
    if not description:
        parser.error("更新说明不能为空")

    root = Path(__file__).resolve().parent.parent
    package_path = root / "frontend/package.json"
    lock_path = root / "frontend/package-lock.json"
    releases_path = root / "backend/releases.json"
    compose_path = root / "compose.server.yaml"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    releases = json.loads(releases_path.read_text(encoding="utf-8"))
    compose = compose_path.read_text(encoding="utf-8")
    if tuple(map(int, args.version.split('.'))) < tuple(map(int, package['version'].split('.'))):
        parser.error("新版本不能低于当前版本；回滚请使用已有镜像")
    if args.version in releases and releases[args.version] != description:
        parser.error("该版本已有不同说明，请使用新版本号")
    # 在写文件前确认两个生产镜像标签都能更新，避免只更新前端而漏记发版。
    for service in ("api", "web"):
        compose, count = re.subn(rf"(image: zhoubao-server-{service}:)\S+", rf"\g<1>{args.version}", compose)
        if count != 1:
            parser.error(f"无法唯一定位 {service} 的生产镜像标签")
    package['version'] = lock['version'] = lock['packages']['']['version'] = args.version
    releases[args.version] = description
    for path, content in ((package_path, package), (lock_path, lock), (releases_path, releases)):
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    compose_path.write_text(compose, encoding="utf-8")
    print(f"已准备版本 {args.version}，请构建并部署 API 和 Web；API 启动时自动写入发版记录。")


if __name__ == "__main__":
    main()
