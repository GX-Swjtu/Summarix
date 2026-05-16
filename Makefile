# Makefile 用于当前 Summarix 项目的本地开发、测试和构建

# 后端镜像名
BACKEND_IMAGE ?= summarix-backend:latest
# 远程镜像名，推送时通过 make push REMOTE_IMAGE=... 传入
REMOTE_IMAGE ?=
# 后端运行命令
UV_RUN := uv run --env-file .env
# 测试运行命令
PYTEST_RUN := uv run
# Python 辅助脚本运行命令
PYTHON_RUN := uv run python
# 插件目录
EXTENSION_DIR := extension
# 监控辅助脚本
MONITORING_TOOL := scripts/monitoring_stack.py

.PHONY: help sync install run backend db-reset test test-api test-file extension-install extension-build extension-dev build push verify monitor-up monitor-down monitor-check monitor-backend-up monitor-backend-down monitor-backend-check monitor-plg-up monitor-plg-down monitor-plg-check monitor-langwatch-up monitor-langwatch-down monitor-langwatch-check monitor-test-api

# 默认目标，展示可用命令
.DEFAULT_GOAL := help

# 命令帮助
help:
	@echo "可用命令："
	@echo "  make sync             - 安装或同步 Python 依赖"
	@echo "  make install          - sync 的别名"
	@echo "  make run              - 直接运行后端服务"
	@echo "  make backend          - 直接运行后端服务"
	@echo "  make db-reset         - 删除并重建数据库，同时初始化管理员账号"
	@echo "  make test             - 运行全部 Python 测试"
	@echo "  make test-api         - 运行 API 测试"
	@echo "  make test-file TEST=tests/api/test_auth.py - 运行指定测试文件或目录"
	@echo "  make extension-install - 安装插件前端依赖"
	@echo "  make extension-build  - 构建浏览器插件"
	@echo "  make extension-dev    - 启动插件前端 Vite 开发服务"
	@echo "  make build            - 构建后端 Docker 镜像"
	@echo "  make push REMOTE_IMAGE=registry.example.com/summarix:tag - 推送镜像"
	@echo "  make verify           - 运行 API 测试并构建插件"
	@echo "  make monitor-up       - 一键启动后端、共享 PostgreSQL/Redis、PLG 和 LangWatch；首次会自动生成 .env.api.key 模板与持久化 secret"
	@echo "  make monitor-check    - 一键检查后端、共享 PostgreSQL/Redis、PLG 和 LangWatch 健康状态，以及 LangWatch 监控 targets、规则和 dashboard"
	@echo "  make monitor-down     - 一键停止后端、共享 PostgreSQL/Redis、PLG 和 LangWatch"
	@echo "  make monitor-backend-up LOCAL_DB=1 - 启动监控用后端 compose，可选同时拉起 deploy/shared 下的 PostgreSQL/Redis"
	@echo "  make monitor-backend-check - 检查监控用后端 compose 健康状态"
	@echo "  make monitor-backend-down LOCAL_DB=1 - 停止监控用后端 compose，可选同时停止共享 PostgreSQL/Redis"
	@echo "  make monitor-plg-up   - 启动 Prometheus/Loki/Grafana 栈，默认加载 LangWatch targets、告警规则和 dashboard"
	@echo "  make monitor-plg-check - 检查 PLG 栈健康状态、Grafana 数据源，以及已接入的 LangWatch 监控项"
	@echo "  make monitor-plg-down - 停止 PLG 栈"
	@echo "  make monitor-langwatch-up - 启动 deploy/langwatch 栈，并自动复用已初始化的 LangWatch secret"
	@echo "  make monitor-langwatch-check - 检查 LangWatch 首页是否可访问"
	@echo "  make monitor-langwatch-down - 停止 LangWatch 栈"
	@echo "  make monitor-test-api - 运行监控、反馈与 trace 相关 API 测试"
	@echo "  提示                  - make monitor-up 只要求填写 .env.api.key；直接 uv run main.py 仍建议使用整理后的 .env"

# 安装或同步 Python 依赖
sync:
	@echo "开始同步 Python 依赖"
	uv sync

# sync 的别名
install: sync

# 启动后端服务
backend:
	@echo "启动 FastAPI 后端，文档地址: http://127.0.0.1:8000/docs"
	$(UV_RUN) main.py

# run 的效果等同于直接启动后端
run: backend

# 删除并重建数据库，同时初始化管理员账号
db-reset:
	@echo "删除并重建数据库，初始化管理员账号"
	$(UV_RUN) python -m app.db.init reset --admin-email "$(or $(ADMIN_EMAIL),admin@admin.com)" --admin-password "$(or $(ADMIN_PASSWORD),adminGaoxin)"

# 运行全部 Python 测试
test:
	@echo "运行全部 Python 测试"
	$(PYTEST_RUN) pytest tests/

# 运行 API 测试
test-api:
	@echo "运行 API 测试"
	$(PYTEST_RUN) pytest tests/api

# 运行指定测试文件或目录
test-file:
	$(if $(strip $(TEST)),,$(error 请使用 make test-file TEST=tests/api/test_auth.py))
	@echo "运行指定测试: $(TEST)"
	$(PYTEST_RUN) pytest $(TEST)

# 安装插件依赖
extension-install:
	@echo "安装插件前端依赖"
	npm --prefix $(EXTENSION_DIR) install

# 构建浏览器插件
extension-build:
	@echo "构建浏览器插件"
	npm --prefix $(EXTENSION_DIR) run build

# 启动插件前端开发服务
extension-dev:
	@echo "启动插件前端开发服务"
	npm --prefix $(EXTENSION_DIR) run dev

# 构建后端镜像
build:
	@echo "构建后端镜像: $(BACKEND_IMAGE)"
	docker build -t $(BACKEND_IMAGE) .

# 推送镜像到远程仓库
push:
	$(if $(strip $(REMOTE_IMAGE)),,$(error 请使用 make push REMOTE_IMAGE=registry.example.com/summarix:tag))
	@echo "推送镜像: $(REMOTE_IMAGE)"
	docker tag $(BACKEND_IMAGE) $(REMOTE_IMAGE)
	docker push $(REMOTE_IMAGE)

# 执行当前项目最常用的验证命令
verify: test-api extension-build

monitor-up:
	@echo "一键启动监控演示环境"
	$(PYTHON_RUN) $(MONITORING_TOOL) all up

monitor-down:
	@echo "一键停止监控演示环境"
	$(PYTHON_RUN) $(MONITORING_TOOL) all down

monitor-check:
	@echo "一键检查监控演示环境"
	$(PYTHON_RUN) $(MONITORING_TOOL) all check

monitor-backend-up:
	@echo "启动监控用后端 compose"
	$(PYTHON_RUN) $(MONITORING_TOOL) backend up $(if $(strip $(LOCAL_DB)),--local-db,)

monitor-backend-down:
	@echo "停止监控用后端 compose"
	$(PYTHON_RUN) $(MONITORING_TOOL) backend down $(if $(strip $(LOCAL_DB)),--local-db,)

monitor-backend-check:
	@echo "检查监控用后端 compose 健康状态"
	$(PYTHON_RUN) $(MONITORING_TOOL) backend check

monitor-plg-up:
	@echo "启动 PLG 监控栈"
	$(PYTHON_RUN) $(MONITORING_TOOL) plg up

monitor-plg-down:
	@echo "停止 PLG 监控栈"
	$(PYTHON_RUN) $(MONITORING_TOOL) plg down

monitor-plg-check:
	@echo "检查 PLG 监控栈健康状态"
	$(PYTHON_RUN) $(MONITORING_TOOL) plg check

monitor-langwatch-up:
	@echo "启动 LangWatch 栈"
	$(PYTHON_RUN) $(MONITORING_TOOL) langwatch up

monitor-langwatch-down:
	@echo "停止 LangWatch 栈"
	$(PYTHON_RUN) $(MONITORING_TOOL) langwatch down

monitor-langwatch-check:
	@echo "检查 LangWatch 栈健康状态"
	$(PYTHON_RUN) $(MONITORING_TOOL) langwatch check

monitor-test-api:
	@echo "运行监控相关 API 测试"
	$(PYTEST_RUN) pytest tests/api/test_monitoring.py tests/api/test_feedback.py tests/api/test_chat_stream.py
