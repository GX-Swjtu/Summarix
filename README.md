# Summarix

Summarix 是一个基于 Chromium Side Panel 的 AI 网页总结插件，配套 FastAPI 后端。插件负责登录、网页正文提取、截图上传、流式聊天、历史查看和模型设置；后端负责用户认证、PostgreSQL 数据存储、ADK agent 调用、LiteLLM 模型切换和 SSE 流式响应。

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

然后把 `.env` 中的 `JWT_SECRET_KEY` 替换为至少 32 个字符的强随机密钥，否则后端会拒绝启动。

2. 启动 PostgreSQL。

```powershell
docker compose up -d postgres
```

3. 安装依赖并启动后端。

```powershell
uv sync
uv run --env-file .env main.py
```

默认服务地址是 `http://127.0.0.1:8000`，OpenAPI 文档地址是 `http://127.0.0.1:8000/docs`。

本地没有模型密钥时，`.env` 里保持 `CHAT_AGENT_MODE=mock` 即可跑通插件与接口流程；接入真实模型后改为 `CHAT_AGENT_MODE=adk`，并按 LiteLLM 供应商要求配置对应环境变量。

## 插件本地运行

```powershell
cd extension
npm install
npm run build
```

然后在 Chrome 或 Edge 的扩展管理页启用开发者模式，加载 `extension/dist`。插件默认请求 `http://127.0.0.1:8000`，也可以在 Side Panel 设置页修改后端地址。

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
- `GET /api/history?offset=0&limit=20` / `GET /api/history/{id}`：分页读取云端历史。
- `GET /api/settings/models` / `PUT /api/settings/models`：读取和更新模型偏好。

## 测试

接口测试使用 SQLite 内存库和 mock 聊天模式，不依赖真实模型 key。

```powershell
uv run --env-file .env pytest tests/api/test_auth.py tests/api/test_artifacts.py tests/api/test_chat_stream.py tests/api/test_history.py tests/api/test_settings.py
```

## GitHub CI / CD

仓库内置两个 GitHub Actions workflow：

- PR 到 `main` 时运行 CI，包含后端 API 测试、后端 Docker 构建校验和插件构建。
- 代码合入 `main` 且涉及 `extension/` 后，会自动构建插件并上传 zip 产物到 GitHub Actions artifact。
- 推送版本标签（例如 `v0.1.0`）时，会重新构建插件并把 zip 附加到对应的 GitHub Release。

插件发布标签必须与 `extension/package.json` 中的 `version` 一致，否则发布 workflow 会失败，避免错发版本。

当前后端 Docker 仅在 CI 中执行构建校验，不做镜像推送或自动部署；如果后续需要发布后端镜像，可以在现有 workflow 基础上继续扩展。

## Docker / Cloud Run 基线

本仓库提供基础 `Dockerfile`，镜像入口为：

```text
uv run --no-dev --env-file .env main.py
```

部署到 Cloud Run 时需要提供 PostgreSQL 连接串、JWT 密钥、Cookie 安全配置、模型供应商密钥和 artifact 根目录。生产环境建议设置：

```text
APP_ENV=production
HOST=0.0.0.0
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=none
CHAT_AGENT_MODE=adk
BROWSER_EXTENSION_ORIGINS=chrome-extension://your-extension-id
```

ADK 会话默认使用 `DATABASE_URL` 通过 `DatabaseSessionService` 持久化到数据库；如果需要独立数据库，可以额外设置 `ADK_DATABASE_URL`。

## 设计说明

更完整的需求、边界和验收标准见 [DESIGN_SPEC.md](DESIGN_SPEC.md)。
