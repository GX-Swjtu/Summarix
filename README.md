# Summarix

[![CI](https://github.com/GX-Swjtu/Summarix/actions/workflows/ci.yml/badge.svg)](https://github.com/GX-Swjtu/Summarix/actions/workflows/ci.yml)

Summarix 是一个基于 Chromium Side Panel 的 AI 网页总结插件，配套 FastAPI 后端。插件负责登录、网页正文提取、截图上传、流式聊天、下一步建议问题、历史查看、模型设置，以及把网页主体文章快捷转换为小红书文案和短视频脚本；后端负责用户认证、PostgreSQL 数据存储、ADK agent 调用、LiteLLM 模型切换和 SSE 流式响应。

## 项目结构

```text
app/                    # FastAPI 后端
	api/                  # 路由、schema、依赖
	auth/                 # 密码哈希、JWT、Cookie、认证服务
	chat/                 # ADK、LiteLLM、artifact、SSE 编排
	core/                 # 配置
	db/                   # SQLAlchemy 模型和连接
extension/              # Chromium 插件前端
	src/background/       # 截图与扩展消息协调
	src/content/          # Readability.js 正文提取
	src/sidepanel/        # React Side Panel
tests/api/              # 按功能拆分的接口测试
```

## 后端本地运行

1. 准备环境文件。

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写 `DATABASE_URL`，使用你已经准备好的 PostgreSQL 地址、账号和密码；再把 `JWT_SECRET_KEY` 替换为至少 32 个字符的强随机密钥，否则后端会拒绝启动。

`.env.example` 默认把 `APP_ENV` 设为 `local`，因此直接本地启动时会保留开发期行为；`APP_RELOAD` 默认留空，留空时 `local`、`development`、`dev` 会自动启用热重载，其它环境默认关闭。如果你想显式覆盖这条规则，可以在 `.env` 中设置 `APP_RELOAD=true` 或 `APP_RELOAD=false`。

`DATABASE_AUTO_CREATE_DATABASE=true` 时，如果 PostgreSQL 服务已存在但目标数据库还没创建，后端会尝试自动建库；这要求当前数据库账号具备建库权限。

`DATABASE_AUTO_CREATE_TABLES=true` 时，后端启动后会对已连接的数据库执行 Alembic 升级到最新版本；它不会启动数据库服务。生产多实例部署建议先用 `make db-upgrade` 或 CI/CD 单独完成升级，再启动或扩容服务。

数据库结构变更统一由 Alembic 管理。常用命令包括：`make db-upgrade` 执行增量升级，`make db-revision MSG="添加字段"` 生成迁移文件，`make db-current` 查看当前版本，`make db-reset` 删除并重建开发库且初始化管理员账号。完整流程见 [文档/数据库升级指南.md](文档/数据库升级指南.md)。

2. 安装依赖并启动后端。

```powershell
uv sync
uv run --env-file .env main.py
```

默认服务地址是 `http://127.0.0.1:8000`，OpenAPI 文档地址是 `http://127.0.0.1:8000/docs`。

本地没有模型密钥时，`.env` 里保持 `CHAT_AGENT_MODE=mock` 即可跑通插件与接口流程；接入真实模型后改为 `CHAT_AGENT_MODE=adk`，并按 LiteLLM 供应商要求配置对应环境变量。

LiteLLM 模型请直接使用 `provider/model` 形式，例如 `dashscope/qwen3.5-flash` 或 `dashscope/qwen3.5-flash`。后端不会再自动补全 provider。

当前推荐通过文件统一配置模型，而不是按任务分别写环境变量。把 `.env.example` 里的 `MODEL_CATALOG_FILE` 指向一个 JSON 文件即可；可直接参考 [config/model-catalog.example.json](config/model-catalog.example.json)。

模型配置文件支持两个顶层字段：`available_models` 和 `suggested_questions_model`。`available_models` 的顺序就是前端聊天输入框旁模型菜单的顺序，第一个模型会作为默认主力模型；`suggested_questions_model` 只用于后台生成下一步建议问题，不会展示给用户。

模型图标默认从 `MODEL_ASSET_ROOT` 指定的本地目录读取，默认目录是仓库根目录下的 `iconResources`。因此你只需要把图标文件放进 `iconResources/`，然后在 JSON 里把 `icon_url` 写成相对路径，例如 `qwen-color.svg` 或 `iconResources/qwen-color.svg`；后端会自动把它转换成前端可直接访问的 URL。

每个可选模型对象至少建议包含：`id`、`name`、`description`、`is_premium`、`icon_url`、`api_base`、`api_key`、`litellm_model`、`supports_thinking_config`、`default_thinking_mode`。其中 `litellm_model` 必填，`default_thinking_mode` 支持 `default`、`enabled`、`disabled`。如果 `supports_thinking_config=false`，前端不会给用户展示 thinking 子菜单。

兼容旧方式时，仍可通过 `MODEL_CATALOG_JSON` 内联 JSON，或继续使用 `TEXT_SUMMARY_MODEL`、`CONVERSATION_MODEL`、`XIAOHONGSHU_MODEL`、`SHORT_VIDEO_SCRIPT_MODEL`、`SUGGESTED_QUESTIONS_MODEL` 等旧环境变量作为兜底；但前端用户选择入口已经统一为“一个主力模型”。

如果已有开发库是在这些模型偏好列加入前创建的，执行 `make db-upgrade` 即可按 Alembic 迁移补齐结构；若不需要保留本地数据，也可以执行 `make db-reset` 重建开发库。

截图和图片不再配置单独的视觉分析模型，会随当前任务交给对应模型处理；聊天界面会在发送图片时提醒用户确认模型支持图像输入。

## 插件本地运行

```powershell
cd extension
npm install
npm run build
```

然后在 Chrome 或 Edge 的扩展管理页启用开发者模式，加载 `extension/dist`。

插件的后端地址优先级如下：

1. 登录页或 Side Panel 设置页里手动填写的后端地址。
2. 编译扩展时通过 `SUMMARIX_DEFAULT_API_BASE` 注入的默认地址。
3. 扩展代码中的兜底默认值 `http://127.0.0.1:8000`。

如果构建出来的默认地址不对，用户可以在登录页先修改后端地址再登录；登录后也可以在设置页继续调整。登录页和设置页都提供“恢复默认”按钮，用来回到编译时默认地址。

如果你希望在构建时写死一个新的默认后端地址，可以在构建前设置环境变量：

```powershell
cd extension
$env:SUMMARIX_DEFAULT_API_BASE = "https://your-backend.example.com"
npm run build
Remove-Item Env:SUMMARIX_DEFAULT_API_BASE
```

```bash
cd extension
SUMMARIX_DEFAULT_API_BASE=https://your-backend.example.com npm run build
```

如果你不想依赖构建环境变量，也可以直接修改 `extension/src/shared/api.ts` 里的兜底默认值 `FALLBACK_API_BASE`，然后重新构建扩展。

加载插件后，把扩展管理页显示的扩展 ID 配置到后端环境变量，例如：

```text
BROWSER_EXTENSION_ORIGINS=chrome-extension://your-extension-id
```

## 主要接口

- `POST /api/auth/register`：注册并下发 access/refresh 双 Cookie。
- `POST /api/auth/login`：登录并下发 access/refresh 双 Cookie。
- `POST /api/auth/refresh`：刷新并轮换 refresh token。
- `POST /api/auth/logout`：退出并吊销当前 refresh token。
- `POST /api/chat/artifacts`：上传截图或其他文件，返回 `artifact_id`。
- `POST /api/chat/stream`：基于文本、网页上下文和 artifact 引用返回 SSE 流。
- `POST /api/chat/suggestions/stream`：基于已有会话返回下一步建议问题 SSE 流。
- `GET /api/history?offset=0&limit=20` / `GET /api/history/{id}`：分页读取云端历史。
- `GET /api/settings/models` / `PUT /api/settings/models`：读取和更新模型偏好。

## 测试

接口测试会强制使用 SQLite 内存库和 mock 聊天模式，不会连接 `.env` 中配置的真实数据库，也不依赖真实模型 key。

```powershell
uv run pytest tests/api/test_auth.py tests/api/test_artifacts.py tests/api/test_chat_stream.py tests/api/test_history.py tests/api/test_settings.py
```

## GitHub CI / CD

仓库内置两个 GitHub Actions workflow：

- PR 到 `master` 或直接推送到 `master` 时运行 CI，包含后端 API 测试、后端 Docker 构建校验和插件构建。
- 代码推送到 `master` 后，会自动把当前插件构建结果打包成 zip 并上传到 GitHub Actions artifact，方便验收主分支最新产物。
- 推送版本标签（例如 `v0.1.0`）时，会先运行完整 Python 测试集 `uv run pytest tests/`，测试通过后再重新构建插件、推送后端 Docker 镜像，并创建对应的 GitHub Release。

发布标签必须与 `extension/package.json` 中的 `version` 一致，否则发布 workflow 会失败，避免错发版本。

Release workflow 会把后端镜像推送到 `ghcr.io/<仓库所有者小写>/summarix-backend:vX.Y.Z` 和 `ghcr.io/<仓库所有者小写>/summarix-backend:latest`，同时把插件 zip 与镜像信息说明文件附加到 GitHub Release。

## Docker / Cloud Run 基线

本仓库提供基础 `Dockerfile`，镜像入口为：

```text
uv run --no-dev --env-file .env main.py
```

部署到 Cloud Run 时需要提供 PostgreSQL 连接串、JWT 密钥、Cookie 安全配置、模型供应商密钥和 artifact 根目录。生产环境建议设置：

```text
APP_ENV=production
APP_RELOAD=false
HOST=0.0.0.0
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=none
CHAT_AGENT_MODE=adk
BROWSER_EXTENSION_ORIGINS=chrome-extension://your-extension-id
```

ADK 会话默认使用 `DATABASE_URL` 通过 `DatabaseSessionService` 持久化到数据库；如果需要独立数据库，可以额外设置 `ADK_DATABASE_URL`。当 `DATABASE_AUTO_CREATE_DATABASE=true` 时，独立的 ADK 数据库在不存在时也会尝试自动创建。

`deploy/backend/compose.yml` 会显式把 `APP_RELOAD` 设为 `false`，所以即使根目录 `.env` 仍是宿主机本地开发配置，这套容器默认也不会启用 Uvicorn 热重载。`.env.example` 只是模板文件，不会被容器直接读取，只有复制或同步到 `.env` 后才会影响运行时。

## 可选监控部署

监控能力默认全部关闭。没有显式设置 `PROMETHEUS_ENABLED=true`、`LOG_FORMAT=json` 或 `LANGWATCH_ENABLED=true` 时，后端不会注册 `/metrics`，不会初始化 LangWatch，也不会向外部监控服务发送请求。

本仓库把监控相关部署统一收敛到 `deploy/` 目录下：

- `deploy/shared/compose.yml` 负责共享 PostgreSQL 和共享 Redis，后端、LangWatch 以及后续新增服务都可以直接复用。
- `deploy/backend/compose.yml` 负责业务后端。
- `deploy/plg/compose.yml` 负责 Prometheus、Loki、Grafana。
- `deploy/langwatch/compose.yml` 负责 LangWatch 和 ClickHouse。

推荐优先使用一键命令。它会自动创建本地持久化目录 `deploy/data/**`，并生成两个运行时文件：

- `deploy/runtime/monitoring.persisted.env`：首次自动生成并固定保存 JWT、LangWatch secret、本地数据库密码、Grafana 管理密码，后续启动会直接复用。
- `deploy/runtime/monitoring.generated.env`：每次启动时根据当前配置重新拼出的最终运行时环境，包含数据库地址、LangWatch 地址、端口、模型模式等。

你只需要手动维护一个文件 `.env.api.key`，里面放 `DASHSCOPE_API_KEY` 和其它你自己掌握的第三方 Key：

```powershell
Copy-Item .env.api.key.example .env.api.key
```

然后填写至少一个模型 Key；如果只填了 `DASHSCOPE_API_KEY`，当前默认 Qwen 配置就能直接工作：

```text
DASHSCOPE_API_KEY=sk-xxx
```

准备好后直接执行：

```powershell
make monitor-up
```

从这一版开始，`make monitor-up` 会默认把 LangWatch 自托管 App 与 Workers 一起接入当前 PLG：

- Prometheus 默认抓取 `summarix-backend:8000`、`langwatch-app:5560`、`langwatch-workers:2999`
- Grafana 默认 provision `Summarix Overview` 和 `LangWatch Overview` 两个 dashboard
- Prometheus 默认加载 `deploy/plg/prometheus/alerts/langwatch-self-hosted.rules.yml` 规则组

这里接入的是 LangWatch 自托管应用本体的监控面，不包含 AI Gateway cookbook 里的 `gateway_*` 指标、dashboard 和告警规则。

`.env.api.key` 不存在时，脚本会自动从 `.env.api.key.example` 生成模板。JWT、LangWatch secret、本地数据库密码、Grafana 密码都不再需要手动填写；首次启动时会自动生成并落盘，后续保持不变。

如果 `.env.api.key` 里还没有 `LANGWATCH_API_KEY`，`make monitor-up` 会先把 LangWatch 页面启动起来，然后按 LangWatch 官方推荐方式引导你：在浏览器里注册或登录、自行创建或选择项目、在项目设置里生成 Project API Key，再把这个 Key 以隐藏输入方式粘贴回终端。脚本会把它写入 `.env.api.key`，后续启动直接复用；这样下次一打开 LangWatch，就能在你自己有权限的项目里看到数据，不再依赖数据库直改权限。

如果 `.env.api.key` 里没有任何模型 Key，脚本仍然可以把整套集群拉起来，但会自动把后端切到 `mock` 模式，方便先验证链路；补上 Key 后，下次 `make monitor-up` 会自动回到真实模型模式。

如果只想按职责启动单独栈，也可以继续使用分项命令：

```powershell
# 后端业务服务，可选 LOCAL_DB=1 同时启动 deploy/shared 下的共享 PostgreSQL
make monitor-backend-up
make monitor-backend-up LOCAL_DB=1

# Prometheus + Loki + Grafana 本地监控栈；Linux 宿主机会自动启用 node-exporter
make monitor-plg-up

# LangWatch 自托管栈；启动时会自动复用之前初始化过的 LangWatch secret
make monitor-langwatch-up

# 监控相关后端测试
make monitor-test-api
```

需要单独停掉某一套服务时，可使用：

```powershell
make monitor-down
make monitor-backend-down
make monitor-plg-down
make monitor-langwatch-down
```

需要只做健康检查、不重启服务时，可使用：

```powershell
make monitor-check
make monitor-backend-check
make monitor-plg-check
make monitor-langwatch-check
```

如果你更想直接使用 raw compose，推荐的等价命令是：

```powershell
docker compose -f deploy/shared/compose.yml up -d
docker compose -f deploy/backend/compose.yml up -d --build
docker compose -f deploy/plg/compose.yml up -d

# 只有 Linux 宿主机才建议显式启用 host-metrics profile，拉起 node-exporter
docker compose --profile host-metrics -f deploy/plg/compose.yml up -d

docker compose -f deploy/langwatch/compose.yml up -d
```

常用端口：后端 `http://127.0.0.1:8000`，PostgreSQL `127.0.0.1:5432`，Redis `127.0.0.1:6379`，Prometheus `http://127.0.0.1:9090`，Grafana `http://127.0.0.1:3000`，LangWatch `https://127.0.0.1:5560`。

如果只先启动 PLG 而没有启动 LangWatch 栈，Prometheus 中与 LangWatch 相关的 targets 会显示为 `down`；这是预期行为。只要随后执行 `make monitor-langwatch-up` 或 `make monitor-up`，`make monitor-plg-check` 就会把它们连同 dashboard 和 rules 一起校验。

Linux 宿主机上，PLG 会优先尝试附带 `host-metrics` profile 启动 `node-exporter` 与 `cadvisor`；如果当前环境无法拉取这些镜像，脚本会自动降级为仅启动核心的 Prometheus、Loki、Grafana，不再因为 host metrics 失败而阻断整套监控链路。

本地持久化目录会统一落在：

- `deploy/data/postgres`
- `deploy/data/redis`
- `deploy/data/backend/artifacts`
- `deploy/data/plg/prometheus`
- `deploy/data/plg/loki`
- `deploy/data/plg/grafana`
- `deploy/data/langwatch/clickhouse`

共享 Redis 会暴露在 Docker 网络内的 `redis:6379`；后续如果新增需要缓存或队列的服务，直接复用这个地址即可。

根目录 `.env.example` 现在已经补齐为当前后端实际支持的主要配置；如果你的本地 `.env` 是较早版本，建议按新的分组结构补齐。当前推荐做法是：

- `.env` 放本地后端基础配置和默认模型配置。
- `.env.api.key` 放第三方 Key。
- `deploy/runtime/monitoring.persisted.env` 放脚本首次生成后固定保存的本地 secret。

启用 Prometheus 指标时，在 `.env` 中设置：

```text
PROMETHEUS_ENABLED=true
PROMETHEUS_METRICS_PATH=/metrics
```

PLG 栈默认抓取 `summarix-backend:8000`。如果后端不在同一个 Docker 网络内，可以在启动 PLG 前设置环境变量：

```powershell
$env:SUMMARIX_METRICS_TARGET = "host.docker.internal:8000"
docker compose -f deploy/plg/compose.yml up -d
```

同理，如果你需要覆盖默认的 LangWatch 抓取目标，也可以在启动 PLG 前设置：

```powershell
$env:LANGWATCH_APP_METRICS_TARGET = "host.docker.internal:5560"
$env:LANGWATCH_WORKERS_METRICS_TARGET = "host.docker.internal:2999"
docker compose -f deploy/plg/compose.yml up -d
```

Prometheus 规则文件位于 `deploy/plg/prometheus/alerts/langwatch-self-hosted.rules.yml`，对应的 Grafana 仪表盘位于 `deploy/plg/grafana/dashboards/langwatch-overview.json`。`make monitor-check` 和 `make monitor-plg-check` 现在都会验证这两项是否已被成功加载。

启用 Loki JSON 日志时，在 `.env` 中设置：

```text
LOG_FORMAT=json
LOG_LEVEL=INFO
```

Promtail 通过 Docker socket 发现容器并读取 Docker 容器日志。Windows Docker Desktop 场景下，这些路径位于 Linux VM 内，使用 `deploy/plg/compose.yml` 的默认挂载即可；如果你的容器运行时不是 Docker Desktop，需要按实际日志路径调整 `deploy/plg/promtail/promtail-config.yaml`。`node-exporter` 现在被放到了 `host-metrics` profile 中，默认启动不会在 Windows Docker Desktop 下报 rootfs 共享挂载错误；只有 Linux 宿主机才建议启用它。

启用 LangWatch 时，可以连接本地自托管或外部 LangWatch：

```text
LANGWATCH_ENABLED=true
LANGWATCH_API_KEY=sk-lw-your-project-key
LANGWATCH_ENDPOINT=http://langwatch:5560
LANGWATCH_PUBLIC_URL=http://127.0.0.1:5560
```

如果你想查看首次生成并固定下来的关键 secret，可以直接打开 `deploy/runtime/monitoring.persisted.env`。其中至少会包含这 4 个 LangWatch 必填 secret：

```text
NEXTAUTH_SECRET=
BETTER_AUTH_SECRET=
CREDENTIALS_SECRET=
API_TOKEN_JWT_SECRET=
```

这些值会在第一次启动时自动生成；只要不删除 `deploy/runtime/monitoring.persisted.env`，以后每次都是同一套值。

`make monitor-up` 会自动把后端 compose 的 `DATABASE_URL` 和 `ADK_DATABASE_URL` 指向 Docker 内的 `postgres:5432`，并把 LangWatch 的 `DATABASE_URL` 自动生成为同一个 PostgreSQL 实例下的 `langwatch` schema；因此除了 `.env.api.key` 里的第三方 Key 以外，不需要再手动填写这些基础设施地址。

用户反馈接口为 `POST /api/feedback`，插件会在助手回复旁显示点赞/点踩按钮。后端会先保存本地反馈记录；如果 LangWatch 启用且有 `trace_id`，会再调用 LangWatch Annotation API，把反馈关联到对应 trace。LangWatch 同步失败不会丢失本地反馈。

监控反馈相关表和字段已经纳入 Alembic 迁移。升级已有环境时先执行 [文档/数据库升级指南.md](文档/数据库升级指南.md) 中的 `make db-upgrade`，再启动或扩容后端服务。

## 设计说明

更完整的需求、边界和验收标准见 [DESIGN_SPEC.md](DESIGN_SPEC.md)。
