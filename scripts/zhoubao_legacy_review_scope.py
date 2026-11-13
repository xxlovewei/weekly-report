"""为 Hermes 的旧 HTML 审查任务生成遵循周报项目配置的提交清单。"""

import argparse
import hashlib
import json
import os
import re
import runpy
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

from zhoubao_daily_review import SHANGHAI, branch_commits, legacy_gitlab, process, read_json, sync_repo


def configured_fetch(day, report_date, output, projects, base, token, cache):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("REVIEW_", "GIT_CONFIG_"))}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    records = []
    for project in projects:
        repo = cache / f"project-{project['id']}"
        sync_repo(project, repo, base, token, env, 480)
        # 旧 OCR 使用 GitLab 的命名空间路径定位镜像。
        path = unquote(project["url"].removeprefix(base + "/").removesuffix(".git"))
        if not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)+", path) or any(part in (".", "..") for part in path.split("/")):
            raise ValueError("审查项目路径无效")
        for sha, branches in branch_commits(repo, env, day, project["skip_slash_branches"]).items():
            author, title, message = process(["git", "show", "-s", "--format=%an%x00%s%x00%B", sha], repo, env, 30).split("\0", 2)
            diff = process(["git", "show", "--format=", "--first-parent", "--no-ext-diff", "--no-textconv", sha], repo, env, 60)
            records.append({"project": path, "project_url": project["url"], "branch": branches[0],
                            "branches": branches, "sha": sha, "short_sha": sha[:8], "author": author,
                            "date": day.isoformat(), "message": title, "full_message": message.strip(), "diffs": diff})
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"commits_{report_date}_raw.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "check-missed", "config"))
    parser.add_argument("report_date", nargs="?", type=date.fromisoformat, default=datetime.now(SHANGHAI).date())
    parser.add_argument("--system-url", default=os.environ.get("REVIEW_SYSTEM_URL"))
    parser.add_argument("--config", type=Path, help="读取部署环境中的 REVIEW_WORKER_TOKEN")
    args = parser.parse_args()
    url = (args.system_url or "").rstrip("/")
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
    ):
        parser.error("周报 API 地址应使用 HTTPS 或本机回环地址")
    token = os.environ.get("REVIEW_WORKER_TOKEN", "")
    if args.config:
        settings = dict(line.split("=", 1) for line in args.config.read_text(encoding="utf-8-sig").splitlines() if "=" in line)
        token = settings.get("REVIEW_WORKER_TOKEN", "")
    if not token:
        parser.error("缺少周报任务令牌")
    headers = {"Authorization": "Bearer " + token}
    for key in ("NO_PROXY", "no_proxy"):
        os.environ[key] = ",".join(filter(None, (os.environ.get(key), "localhost", "127.0.0.1")))
    projects = read_json(f"{url}/api/reviews/worker/projects", headers)["projects"]
    if args.command == "config":
        print(json.dumps(projects, ensure_ascii=False))
        return
    legacy_dir = Path.home() / "code-review"
    credentials = legacy_gitlab(legacy_dir / "daily_fetch.py")
    base, token = credentials["GITLAB_URL"].rstrip("/"), credentials["TOKEN"]
    output = Path(os.environ["CODE_REVIEW_DIR"])
    cache = Path.home() / "zhoubao-review-legacy"
    signature = hashlib.sha256(json.dumps(projects, sort_keys=True).encode()).hexdigest()

    def scope_file(report_date):
        return output / f"commits_{report_date}_scope.txt"

    # 旧 HTML 流程以日报日期命名文件，其中的提交来自上海时区前一天。
    def fetch_for_report(report_date):
        commit_day = date.fromisoformat(report_date) - timedelta(days=1)
        count = configured_fetch(commit_day, report_date, output, projects, base, token, cache)
        scope_file(report_date).write_text(signature, encoding="ascii")
        return count

    if args.command == "check-missed":
        checker = runpy.run_path(str(legacy_dir / "check_missed.py"))
        namespace = checker["main"].__globals__
        raw_size = namespace["raw_size"]

        def configured_size(report_date):
            marker = scope_file(report_date)
            if marker.is_file() and marker.read_text(encoding="ascii") == signature:
                return raw_size(report_date)
            return None

        # 无 HTML 的历史 raw 可能来自旧全量扫描，按当前配置重新采集后才能补审。
        namespace["raw_size"] = configured_size
        namespace["fetch_date"] = fetch_for_report
        checker["main"]()
    else:
        print(f"Total new commits: {fetch_for_report(args.report_date.isoformat())}")


if __name__ == "__main__":
    main()
