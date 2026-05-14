# Repository Guidelines

## Pandora 黑盒约束
`pandora/` 目录是严格黑盒，任何 agent 都不允许查看其中代码，也不允许分析、推断或讨论其内部实现。

当仓库其他模块调用 `pandora/` 目录对外暴露的函数、类或其他接口时，只能把这些内容当作外部黑盒接口使用，只接受其输入输出与调用方式，不得基于调用点继续推测内部逻辑。

如果某项任务依赖 `pandora/` 目录的内部行为、实现细节或调试能力，agent 必须停留在接口层说明限制，并交由仓库所有者处理，不得自行深入。

## 项目结构与模块组织
本项目是一个求职助手，按能力拆分为 4 个核心目录：`boss/` 负责 Boss 直聘站点自动化，覆盖登录、职位采集和 Boss 聊天；`mcp/` 负责对 Hermes 暴露 MCP 服务与工具；`web/` 负责数据查看与运营面板；`tests/` 存放对应模块测试。公共配置建议放在 `config/`，一次性脚本放在 `scripts/`。

模块边界要清晰：浏览器控制、业务规则、MongoDB 读写不要混写在同一个文件里。新增能力时优先沿现有模块扩展，不要把跨模块逻辑堆到入口脚本。

## 构建、测试与开发命令
- `uv sync`：安装或更新项目依赖。
- `uv run python main.py`：运行默认入口，适合本地快速验证。
- `uv run pytest`：运行全部测试。
- `uv run pytest tests/boss`：只验证 Boss 自动化相关逻辑。
- `uv run python -m playwright install`：初始化浏览器依赖。

如果后续补充 `web/` 独立前端工程，应在该目录内提供单独的启动和构建命令，并同步更新本文档。

## 编码风格与命名约定
项目以 Python 为主，目标版本与 `pyproject.toml` 保持一致。统一使用 4 空格缩进，函数、变量、模块使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。MongoDB collection 名称、MCP tool 名称、前端消费字段应保持语义一致，例如 `jobs`、`chat_sessions`、`resume_match_score`。

Playwright 页面对象、MCP tool 定义、数据访问层应分目录管理。避免把选择器、接口协议和数据库模型硬编码到同一处。

`scripts/` 目录下的代码风格优先简单直接，不需要引入命令行参数工具；非必要不要做函数封装；以可读性优先，不额外考虑安全、性能和设计层面的抽象。

## 测试指南
测试文件放在 `tests/` 下，命名使用 `test_<feature>.py`。Boss 自动化重点覆盖登录态处理、页面流程和选择器稳定性；MCP 重点覆盖输入输出结构、异常分支和 Hermes 调用契约；MongoDB 相关测试要验证文档结构和读写行为。新增功能至少补充一条成功路径测试，关键失败场景也要覆盖。

`scripts/` 目录下的独立调试脚本、一次性辅助脚本默认不要求补测试，除非仓库所有者明确提出。

## 提交与 Pull Request 规范
提交信息使用祈使句，保持单一主题，例如 `Add boss job crawler service`。PR 描述需明确影响范围是 `boss`、`mcp`、`web` 中的哪一块，说明本地验证方式，并在涉及页面流程时附截图或关键日志。若修改了 MCP 接口、MongoDB 文档结构或前端展示字段，必须在 PR 中写明兼容性影响与迁移方式。
