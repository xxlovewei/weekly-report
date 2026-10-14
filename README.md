# 周报 / WEEKLY REPORT

Vue 3 + FastAPI + PostgreSQL 的小型周报系统。前端和 API 通过同一入口提供服务；周一为每周第一天。个人可编辑自己的任务与任务类型，所有登录用户可查看普通用户周报，并共同维护会议记录。

## 本地 Docker Desktop 启动

1. 复制 `.env.example` 为 `.env`，将 `POSTGRES_PASSWORD` 换成随机强密码，并把同一个密码填入 `DATABASE_URL`。密码若含 URL 保留字符，需要先进行 URL 编码。
2. 确认 `127.0.0.1:18080` 未被占用，然后在本目录执行：

   ```sh
   docker compose -p zhoubao-01a13375 up -d --build
   docker compose -p zhoubao-01a13375 ps
   ```

3. 创建第一位管理员：

   ```sh
   docker compose -p zhoubao-01a13375 exec api python -m app.bootstrap
   ```

   命令交互读取用户名、姓名及密码（至少 6 位），不会提供默认账号。随后打开 <http://127.0.0.1:18080>。

开发项目使用专属 Compose 名称、网络及数据库卷。数据库和 API 没有宿主机端口；其他 Compose 项目不会被启动、停止或清理。停止本项目使用 `docker compose -p zhoubao-01a13375 down`，该命令保留数据卷。**不要添加 `-v`，除非明确要删除本项目数据。**

## 开发和测试

前端在 `frontend/`：`npm ci`、`npm run build`、`npm test`。后端在 `backend/`：按 `requirements.txt` 安装依赖，设置 `DATABASE_URL`，执行 `alembic upgrade head`。浏览器测试在 `frontend/` 运行 `npm run test:e2e`，默认访问 `http://127.0.0.1:18081` 的专属测试项目。

测试数据库与开发数据库隔离：

```powershell
$env:APP_PORT = '18081'
docker compose -p zhoubao-01a13375-test -f compose.yaml -f compose.test.yaml up -d --build
```

测试数据库只绑定 `127.0.0.1:15433`。运行后端测试时，将 `.env` 中的数据库密码代入 `TEST_DATABASE_URL=postgresql+psycopg://zhoubao:<密码>@127.0.0.1:15433/zhoubao`，再从 `backend/` 运行 `python -m pytest -q`。浏览器测试前，把相同地址设置为 `DATABASE_URL`，运行 `python -m tests.seed_e2e`；此命令只重置测试数据库并建立三个测试账号。后端测试和浏览器种子程序都会拒绝非测试端口，以避免误清空其他数据库。

## 设计与数据约定

- 周标识是周一日期，格式 `YYYY-MM-DD`；工作日是 1–7 的数组（周一为 1）。
- 完成状态可为空；界面显示“未开始”，跨周复制时视为未完成。
- 任务类型包含六个所有人可选的内置类型，以及个人维护的类型。任务保存类型名称快照，字典改名或删除不修改历史任务；任务大类是独立文本字段。
- 停用用户保留历史记录；停用和密码重置会撤销会话。
- 用户状态默认为“正常”；管理员可改为“锁定”，锁定账号无法登录并提示“账号已锁定，请联系管理员。”，已有会话同步撤销。
- 同一账号滚动 5 分钟内第 6 次密码错误会自动锁定（用户名不区分大小写，成功登录不清除窗口内错误）。状态与计数持久化，锁定不会随时间自动解除；管理员改回“正常”后清空错误记录。不能手动锁定最后一位有效管理员。
- 新建用户及重置密码后的用户必须先修改初始密码，新密码不能与初始密码相同。管理员不在周报汇总中展示。
- 月历仅查询当前显示的六周任务标记；绿色 √ 表示该周有任务。会议记录对所有登录用户开放，按日期倒序分页，支持日期、内容及关联任务状态筛选。
- 自动保存具有修订号保护，遇到其他标签页修改时会提示冲突。
- 本周工作新增、修改任务时，任务描述中以 `1.`、`1、`、`1)`、`(1)`、`（1）` 等数字序号开头的行，按 Enter 会续写下一序号并保留缩进、分隔符及空格；Shift+Enter 可普通换行。

API 文档在登录后的 `/api/docs`；所有受保护的写请求需要 `X-CSRF-Token`，登录和 `/api/auth/me` 返回该值。新增、复制行及跨周复制支持 `Idempotency-Key` 请求头。

## 发布版本号

登录后的侧栏版本号读取 `frontend/package.json` 的 `version`。每次发布前在 `frontend` 目录执行 `npm version <新版本号> --no-git-tag-version`，同步更新项目版本与锁文件，再构建发布。本次版本为 `1.0.3`。
