# Job Buddy

本地部署的求职助手骨架项目，使用：

- `FastAPI` 提供 Web 管理台和 REST API
- `FastMCP` 提供只读 MCP 工具
- `MongoDB` 存储目标岗位、职位线索、任务记录和会话摘要
- BOSS 直聘网站操控能力基于 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli) 项目

## 功能范围

- 目标岗位配置 CRUD
- 手动触发职位采集任务
- 手动触发打招呼任务
- 职位池、任务记录、会话摘要查询
- 本地静态 SPA 管理台
- MCP 只读查询工具

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
uv run uvicorn job_buddy.main:app --reload --host 0.0.0.0 --port 8000
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
  mcp.py          FastMCP 服务
  modules/        按业务域组织的模型、查询和业务逻辑
  routers/        REST API 路由
  web/            嵌入式静态前端
tests/            基础测试
web/src/          前端源码占位
scripts/          本地脚本
```

## 第三方 BOSS 模块接入

当前项目中的 BOSS 直聘网站操控能力基于 [`boss-agent-cli`](https://github.com/can4hou6joeng4/boss-agent-cli)。

目前已经真实接通的是环境诊断链路，即通过 `boss --json doctor` 检查本地运行环境、依赖和登录条件，并在网页页面中展示诊断结果。

搜索、打招呼、会话同步等其它 BOSS 业务能力本轮未调整，仍沿用当前项目内部既有抽象。

当前保留了项目内部的 BOSS 抽象和本地 stub，用于测试和开发占位；BOSS CLI 相关环境变量如下：

- `BOSS_CLI_BIN=boss`
- `BOSS_DATA_DIR=`
- `BOSS_CDP_URL=`
