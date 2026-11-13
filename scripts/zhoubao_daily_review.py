"""从周报读取项目配置，审查上海时区前一天的 GitLab 提交并提交日报。"""

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SHANGHAI = timezone(timedelta(hours=8))
SEVERITIES = {"critical": "严重", "high": "高危", "medium": "中危", "low": "低危", "info": "提示"}
CATEGORIES = {
    "security": ("安全", "安全性"), "performance": ("性能", "性能"),
    "testability": ("测试", "可测试性"), "maintainability": ("可维护性", "代码质量"),
    "style": ("代码风格", "代码质量"), "bug": ("缺陷", "代码质量"),
}
REVIEW_BACKGROUND = """这是中文代码审查日报。每条审查意见的 content 必须用简体中文，依次包含三个独立段落：
问题描述：用一句话概括具体缺陷。
风险说明：说明触发条件和影响。
修改建议：说明改哪个位置、怎么改、为什么，并用中文说明建议代码的作用。
标识符、文件路径和代码保持原文。示例代码仅放在 suggestion_code，修改建议的中文说明仍须填写。
"""
REVIEW_FIELDS = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?\*{0,2}(问题描述|风险说明|修改建议)\*{0,2}[：:]\s*\*{0,2}\s*")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_json(url, headers, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    headers = {**headers, **({"Content-Type": "application/json"} if body is not None else {})}
    with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers), timeout=45) as response:
        return json.load(response)


def legacy_gitlab(path):
    # 复用既有本机凭据配置，只读取字符串赋值，避免执行旧流程。
    result = {}
    if path:
        for statement in ast.parse(Path(path).read_text(encoding="utf-8-sig")).body:
            if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Constant):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in {"GITLAB_URL", "TOKEN"}:
                    result[target.id] = statement.value.value
    return result


def process(command, repo, env, timeout):
    return subprocess.run(command, cwd=repo, env=env, timeout=max(1, timeout), check=True,
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def safe_remote(value, gitlab_base):
    parsed = urlsplit(value)
    base = urlsplit(gitlab_base)
    return (parsed.scheme, parsed.netloc) == (base.scheme, base.netloc) and parsed.path.startswith(
        base.path.rstrip("/") + "/"
    ) and parsed.username is None and not parsed.query and not parsed.fragment and not any(c in value for c in "\r\n\\")


def sync_repo(project, repo, base, token, env, timeout):
    url = project["url"]
    if project.get("gitlab_url") not in (None, base) or not safe_remote(url, base):
        raise ValueError("项目地址与本机配置的 GitLab 实例不一致")
    identifier = project.get("gitlab_id") or quote(urlsplit(url).path.removeprefix(urlsplit(base).path).strip("/").removesuffix(".git"), safe="")
    metadata = read_json(f"{base}/api/v4/projects/{identifier}", {"PRIVATE-TOKEN": token})
    remote = metadata["http_url_to_repo"]
    if not safe_remote(remote, base):
        raise ValueError("GitLab 返回了非本实例的 Git 仓库地址")
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").is_dir():
        process(["git", "init", "--quiet", "--template="], repo, env, 30)
    auth = base64.b64encode(f"oauth2:{token}".encode()).decode()
    fetch_env = {**env, "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "http.extraHeader",
                 "GIT_CONFIG_VALUE_0": "Authorization: Basic " + auth,
                 "GIT_CONFIG_KEY_1": "http.followRedirects", "GIT_CONFIG_VALUE_1": "false"}
    process(["git", "fetch", "--quiet", "--no-tags", "--prune", "--", remote,
             "+refs/heads/*:refs/remotes/review/*"], repo, fetch_env, timeout)


def branch_commits(repo, env, day, skip_slash_branches):
    start = datetime.combine(day, clock_time.min, SHANGHAI)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    prefix = "refs/remotes/review/"
    refs = process(["git", "for-each-ref", "--format=%(refname)", prefix], repo, env, 60).splitlines()
    result = defaultdict(list)
    for ref in refs:
        branch = ref.removeprefix(prefix)
        if skip_slash_branches and "/" in branch:
            continue
        args = ["git", "log", "--format=%H", f"--since-as-filter={start.isoformat()}", f"--until={end.isoformat()}", ref, "--"]
        for sha in process(args, repo, env, 60).splitlines():
            result[sha].append(branch)
    return result


def author_login(name, email, known):
    prefix = re.sub(r"^\d+-", "", email.partition("@")[0])
    for candidate in (name, prefix):
        if candidate.lower() in known:
            return known[candidate.lower()]
    return name or prefix


def positive_signals(repo, sha, author, env):
    # 仅依据实际新增行给出可验证的评价，避免把未验证的代码改动描述为已通过测试。
    counts = defaultdict(int)
    for row in process(["git", "show", "--format=", "--numstat", "--first-parent", sha], repo, env, 45).splitlines():
        fields = row.split("\t", 2)
        if len(fields) != 3 or not fields[0].isdigit() or fields[0] == "0":
            continue
        path = fields[2].lower()
        if re.search(r"(^|/)(tests?|spec|__tests__)/|(?:[._](?:spec|test)\.|test_|test\.java$)", path):
            counts["测试相关文件"] += 1
        elif path.endswith((".md", ".rst", ".adoc")) or "/docs/" in path:
            counts["项目文档"] += 1
    return [f"补充或更新 {count} 个{label} · {sha[:8]} · 修改人：{author or '无名氏'}"
            for label, count in counts.items()]


@contextmanager
def review_environment(env):
    # OCR 的语言设置随配置文件生效，任务使用临时副本以免影响其他 OCR 调用。
    with tempfile.TemporaryDirectory(prefix="zhoubao-ocr-") as folder:
        target = Path(folder) / ".opencodereview"
        target.mkdir()
        source = Path.home() / ".opencodereview"
        config = source / "config.json"
        settings = json.loads(config.read_text(encoding="utf-8-sig")) if config.is_file() else {}
        settings["language"] = "简体中文"
        (target / "config.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        if (source / "rule.json").is_file():
            shutil.copyfile(source / "rule.json", target / "rule.json")
        background = Path(folder) / "review-context.md"
        background.write_text(REVIEW_BACKGROUND, encoding="utf-8")
        home_key = "USERPROFILE" if os.name == "nt" else "HOME"
        yield {**env, home_key: folder, "OCR_NO_UPDATE": "1"}, background


def finding(project_id, day, commit, comment, occurrence):
    content = (comment.get("content") or "").strip()
    parts = REVIEW_FIELDS.split(content)
    fields = {key: value.strip() for key, value in zip(parts[1::2], parts[2::2])}
    risk = fields.get("风险说明") or (parts[0].strip() if len(parts) > 1 else content) or fields.get("问题描述") or "OCR 未返回风险说明"
    title = fields.get("问题描述") or re.split(r"[。！？\n]|(?<=[.!?])\s", risk, maxsplit=1)[0].strip(" #*")
    category = comment.get("category") or ""
    category_label, dimension = CATEGORIES.get(category, (category, "代码质量"))
    suggestion = fields.get("修改建议", "")
    path = comment.get("path") or ""
    anchor = (path, comment.get("start_line"), comment.get("end_line"), category)
    occurrence[anchor] += 1
    key = json.dumps([str(day), project_id, commit["sha"], anchor, occurrence[anchor]], ensure_ascii=False)
    return {
        "project_id": project_id, "fingerprint": hashlib.sha256(key.encode()).hexdigest(),
        "author": commit["author"], "title": title[:240] or "OCR 审查意见",
        "severity": SEVERITIES.get(comment.get("severity"), "提示"), "category": category_label[:250],
        "dimension": dimension, "sha": commit["sha"], "commit_message": commit["message"],
        "path": path[:4000], "start_line": comment.get("start_line"), "end_line": comment.get("end_line"),
        "existing_code": (comment.get("existing_code") or "")[:30000], "risk": risk[:30000], "suggestion": suggestion[:30000],
        "suggestion_code": (comment.get("suggestion_code") or "")[:30000],
    }


def review_commit(ocr, repo, sha, output, env, review_env, background, timeout):
    output.unlink(missing_ok=True)
    process(["git", "checkout", "--quiet", "--detach", "--force", sha], repo, env, min(90, timeout))
    try:
        process([ocr, "review", "--repo", str(repo), "--commit", sha, "--format", "json", "--audience", "agent",
                 "--background-file", str(background),
                 "--effort", "low", "--max-tokens", "40000", "--timeout", "6", "--output", str(output)],
                repo, review_env, timeout)
    except subprocess.CalledProcessError:
        if not output.is_file():
            raise
    return json.loads(output.read_text(encoding="utf-8-sig"))


def collect(projects, day, report_day, cache, base, token, ocr, env, known, review_env, background):
    started = time.monotonic()
    deadline = started + int(os.environ.get("REVIEW_BUDGET_SECONDS", "2700"))
    summaries, issues, models = [], [], set()
    for project in projects:
        project_id = project["id"]
        summary = {"project_id": project_id, "alias": project["alias"], "commits": [], "positives": []}
        summaries.append(summary)
        if time.monotonic() >= deadline:
            summary["error"] = "超过日报审查时长预算，未读取项目"
            continue
        repo = cache / f"project-{project_id}"
        try:
            sync_repo(project, repo, base, token, env, min(480, deadline - time.monotonic()))
            commits = branch_commits(repo, env, day, project["skip_slash_branches"])
        except ValueError as error:
            summary["error"] = str(error)
            continue
        except (OSError, subprocess.SubprocessError):
            summary["error"] = "无法获取 GitLab 项目或提交，请检查仓库权限和网络连接"
            continue
        for sha, branches in commits.items():
            commit = {"sha": sha, "branches": branches, "author": "", "title": "", "status": "failed"}
            summary["commits"].append(commit)
            try:
                name, email, title, message = process(
                    ["git", "show", "-s", "--format=%an%x00%ae%x00%s%x00%B", sha], repo, env, 30,
                ).split("\0", 3)
                author = author_login(name, email, known)[:250]
                commit.update(author=author, title=title[:5000])
                summary["positives"].extend(positive_signals(repo, sha, author, env))
                remaining = int(deadline - time.monotonic())
                if remaining < 30:
                    commit.update(status="skipped", reason="超过日报审查时长预算")
                    continue
                raw = review_commit(ocr, repo, sha, cache / "ocr-result.json", env, review_env, background, min(remaining, 450))
                model = (raw.get("llm") or {}).get("model")
                if model:
                    models.add(model)
                comments = raw.get("comments") or []
                status = raw.get("status")
                # 保留 OCR 实际覆盖和耗时，缺失的指标由日报按未记录处理。
                metrics = raw.get("summary") or {}
                commit.update(ocr_comments=len(comments), ocr_elapsed=(metrics.get("elapsed") or "")[:80])
                failed_items = re.search(r"(\d+) of (\d+) selected item\(s\) failed", raw.get("message") or "")
                if failed_items:
                    commit.update(ocr_items_failed=int(failed_items[1]), ocr_items_selected=int(failed_items[2]))
                if status == "complete":
                    commit["status"] = status
                elif status == "partial" or comments:
                    commit.update(status="partial", reason="OCR 只完成了部分审查")
                else:
                    commit["reason"] = "OCR 未完成审查"
                occurrence = defaultdict(int)
                issues.extend(finding(project_id, report_day, {**commit, "message": message[:10000]}, comment, occurrence)
                              for comment in comments)
            except (OSError, subprocess.SubprocessError, ValueError):
                commit["reason"] = "Git 或 OCR 运行失败或超时"
    return {"report_date": report_day.isoformat(), "commit_date": day.isoformat(),
            "duration_seconds": round(time.monotonic() - started), "model": "、".join(sorted(models))[:400] or "未取得模型信息",
            "projects": summaries, "issues": issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", type=date.fromisoformat, default=datetime.now(SHANGHAI).date())
    parser.add_argument("--rebuild", action="store_true", help="重新运行指定日报的 OCR")
    args = parser.parse_args()
    url = os.environ.get("REVIEW_SYSTEM_URL", "").rstrip("/")
    worker_token = os.environ.get("REVIEW_WORKER_TOKEN", "")
    if not url or not worker_token:
        raise RuntimeError("缺少 REVIEW_SYSTEM_URL 或 REVIEW_WORKER_TOKEN")
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
    ):
        raise RuntimeError("周报写入地址应使用 HTTPS，或使用本机回环地址")
    default_legacy = Path.home() / "code-review" / "daily_fetch.py"
    legacy_source = os.environ.get("REVIEW_GITLAB_LEGACY_SOURCE", str(default_legacy) if default_legacy.is_file() else "")
    legacy = legacy_gitlab(legacy_source) if not (os.environ.get("REVIEW_GITLAB_URL") and os.environ.get("REVIEW_GITLAB_TOKEN")) else {}
    gitlab = os.environ.get("REVIEW_GITLAB_URL", legacy.get("GITLAB_URL", "")).rstrip("/")
    token = os.environ.get("REVIEW_GITLAB_TOKEN", legacy.get("TOKEN", ""))
    cache = Path(os.environ.get("REVIEW_WORK_DIR", Path.home() / "zhoubao-review")).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": "Bearer " + worker_token}
    worker = f"{url}/api/reviews/worker"
    # 有待写入结果时优先重投，接口故障恢复后无需重新消耗 OCR 调用。
    for pending in sorted(cache.glob("*.pending.json")):
        read_json(f"{worker}/reports", headers, json.loads(pending.read_text(encoding="utf-8")))
        pending.replace(pending.with_name(pending.name.replace(".pending.json", ".json")))
    completed = cache / f"{args.report_date}.json"
    if completed.exists() and not args.rebuild:
        print(f"{args.report_date} 日报已写入")
        return
    config = read_json(f"{worker}/projects", headers)
    projects = config["projects"]
    if projects and (not gitlab or not token):
        raise RuntimeError("缺少本机 GitLab 实例地址或只读访问令牌")
    ocr = os.environ.get("REVIEW_OCR_PATH") or shutil.which("ocr.cmd" if os.name == "nt" else "ocr")
    if projects and not ocr:
        raise RuntimeError("找不到 OCR 可执行文件，请检查 PATH 或 REVIEW_OCR_PATH")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REVIEW_", "GIT_CONFIG_"))}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    known = {name.lower(): name for name in config["usernames"]}
    with review_environment(env) as (review_env, background):
        report = collect(projects, args.report_date - timedelta(days=1), args.report_date, cache, gitlab, token, ocr,
                         env, known, review_env, background)
    pending = cache / f"{args.report_date}.pending.json"
    temp = pending.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    temp.replace(pending)
    read_json(f"{worker}/reports", headers, report)
    pending.replace(completed)
    print(f"{args.report_date} 日报已写入 · {len(projects)} 个项目 · {len(report['issues'])} 个问题")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        # 网络错误仅打印类型/状态，不打印请求头、凭据或 Git 子进程输出。
        print(f"周报代码审查失败：{type(error).__name__} {getattr(error, 'code', '')} "
              f"{error if isinstance(error, RuntimeError) else ''}", file=sys.stderr)
        raise SystemExit(1)
