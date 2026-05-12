# Makefile 用于当前 Summarix 项目的本地开发、测试和构建

# 后端镜像名
BACKEND_IMAGE ?= summarix-backend:latest
# 远程镜像名，推送时通过 make push REMOTE_IMAGE=... 传入
REMOTE_IMAGE ?=
# compose 文件
COMPOSE_FILE := compose.yaml
COMPOSE_CMD := docker compose -f $(COMPOSE_FILE)
# 后端运行命令
UV_RUN := uv run --env-file .env
# 插件目录
EXTENSION_DIR := extension

.PHONY: help sync install run backend db-up db-down db-reset restart stop logs status test test-api test-file extension-install extension-build extension-dev build push verify

# 默认目标，展示可用命令
.DEFAULT_GOAL := help

# 命令帮助
help:
	@echo "可用命令："
	@echo "  make sync             - 安装或同步 Python 依赖"
	@echo "  make install          - sync 的别名"
	@echo "  make db-up            - 启动本地 PostgreSQL"
	@echo "  make db-down          - 停止本地 PostgreSQL"
	@echo "  make db-reset         - 删除本地 PostgreSQL 数据卷后重建数据库"
	@echo "  make restart          - 重启本地 PostgreSQL 容器"
	@echo "  make run              - 启动 PostgreSQL 后运行后端"
	@echo "  make backend          - 直接运行后端服务"
	@echo "  make stop             - stop 的效果等同于 db-down"
	@echo "  make logs             - 查看 PostgreSQL 日志（跟随）"
	@echo "  make status           - 查看 compose 服务状态"
	@echo "  make test             - 运行全部 Python 测试"
	@echo "  make test-api         - 运行 API 测试"
	@echo "  make test-file TEST=tests/api/test_auth.py - 运行指定测试文件或目录"
	@echo "  make extension-install - 安装插件前端依赖"
	@echo "  make extension-build  - 构建浏览器插件"
	@echo "  make extension-dev    - 启动插件前端 Vite 开发服务"
	@echo "  make build            - 构建后端 Docker 镜像"
	@echo "  make push REMOTE_IMAGE=registry.example.com/summarix:tag - 推送镜像"
	@echo "  make verify           - 运行 API 测试并构建插件"
	@echo "  提示                  - 首次运行前请先复制 .env.example 为 .env"

# 安装或同步 Python 依赖
sync:
	@echo "开始同步 Python 依赖"
	uv sync

# sync 的别名
install: sync

# 启动本地 PostgreSQL
db-up:
	@echo "启动本地 PostgreSQL"
	$(COMPOSE_CMD) up -d postgres

# 停止本地 PostgreSQL
db-down:
	@echo "停止本地 PostgreSQL"
	$(COMPOSE_CMD) down

# 删除数据库卷并重新启动 PostgreSQL
db-reset:
	@echo "删除本地 PostgreSQL 数据卷并重建数据库"
	$(COMPOSE_CMD) down -v
	$(COMPOSE_CMD) up -d postgres

# 重启本地 PostgreSQL
restart: db-down db-up

# stop 的效果等同于停止 PostgreSQL
stop: db-down

# 查看 PostgreSQL 日志
logs:
	@echo "查看 PostgreSQL 日志（跟随）"
	$(COMPOSE_CMD) logs -f postgres

# 查看 compose 服务状态
status:
	@echo "查看 compose 服务状态"
	$(COMPOSE_CMD) ps

# 启动后端服务
backend:
	@echo "启动 FastAPI 后端，文档地址: http://127.0.0.1:8000/docs"
	$(UV_RUN) main.py

# 启动数据库后运行后端
run: db-up backend

# 运行全部 Python 测试
test:
	@echo "运行全部 Python 测试"
	$(UV_RUN) pytest tests/

# 运行 API 测试
test-api:
	@echo "运行 API 测试"
	$(UV_RUN) pytest tests/api

# 运行指定测试文件或目录
test-file:
	$(if $(strip $(TEST)),,$(error 请使用 make test-file TEST=tests/api/test_auth.py))
	@echo "运行指定测试: $(TEST)"
	$(UV_RUN) pytest $(TEST)

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
