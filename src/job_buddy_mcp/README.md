# Job Buddy MCP

这是 Job Buddy 的独立 MCP adapter。

它通过 HTTP 调用主应用 REST API，不直接访问数据库或业务服务层。

## 运行方式

先启动主应用，再运行：

```bash
API_BASE_URL=http://localhost:8000 uv run job-buddy-mcp
```

## 目录说明

- `server.py`: MCP 工具实现与入口
- `__init__.py`: 包导出
