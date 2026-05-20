# Job Buddy

本地部署的求职助手骨架项目，使用：

- `FastAPI` 提供 Web 管理台和 REST API
- `FastMCP` 提供面向 agent 的 MCP 工具层
- `MongoDB` 存储目标岗位、职位线索、任务记录和会话摘要
- BOSS 直聘网站操控能力当前基于 `Patchright` 实现，README 中声明参考了 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli) 项目

## 功能范围

- 目标岗位配置 CRUD
- 手动触发职位采集任务
- 手动触发打招呼任务
- 职位池、任务记录、会话摘要查询
- 本地静态 SPA 管理台
- MCP agent 工具层

## 快速开始

1. 创建虚拟环境

```bash
uv venv --seed
```

2. 安装依赖

```bash
uv sync
```

如需同时安装开发工具（包含 `pre-commit`），使用：

```bash
uv sync --extra dev
```

3. 配置环境变量

```bash
cp .env.example .env
```

4. 启动 MongoDB

```bash
docker compose up -d mongodb
```

5. 启动应用

```bash
uv run uvicorn job_buddy.main:app \
  --reload \
  --reload-dir src \
  --reload-dir tests \
  --reload-exclude 'logs/*' \
  --reload-exclude 'data/*' \
  --reload-exclude '.venv/*' \
  --host 0.0.0.0 \
  --port 8000
```

## 测试与提交检查

日常开发建议在提交前执行下面两步：

1. 运行自动化测试

```bash
uv run pytest
```

或使用项目脚本：

```bash
bash scripts/test.sh
```

2. 安装并执行 `pre-commit` 检查

首次启用：

```bash
uv run pre-commit install
```

手动检查全部文件：

```bash
uv run pre-commit run --all-files
```

当前仓库的 `pre-commit` 会执行：

- 基础文本检查：尾随空格、文件结尾换行、YAML 格式、冲突标记
- `pytest` 回归测试，确保提交前至少通过一轮自动化测试

## 项目约定

- 项目文档优先使用中文
- Web 页面文案优先使用中文

## 目录

```text
src/job_buddy/
  main.py         FastAPI 应用入口
  core/           配置、日志、数据库生命周期、BOSS 基础能力
  deps.py         依赖注入
  mcp_server.py   FastMCP 服务
  modules/        按业务域组织的模型、查询和业务逻辑
  routers/        REST API 路由
  web/            嵌入式静态前端
tests/            基础测试
web/src/          前端源码占位
scripts/          本地脚本
```

## 参考项目

当前项目的 BOSS 直聘页面协议理解与字段设计参考了 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli)，但运行时代码已经不再依赖该项目。

当前搜索与登录链路由项目内的 `Patchright` 实现承担，协议常量和字段映射也已内置在仓库代码中。
