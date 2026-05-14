# job-buddy

父仓库负责聚合各模块；其中 `boss/` 已拆分为独立 Git 子项目，并以 submodule 方式接入。

## 初始化

```bash
git submodule update --init --recursive
```

## 运行 `boss`

```bash
uv run python main.py login
```

这会转发到 `boss/` 子项目执行 `python -m boss`。

## `boss` 子项目

```bash
cd boss
uv sync
uv run pytest
uv run python -m boss login
uv run python -m playwright install
```

所有 Playwright、浏览器操控和相关测试、调试脚本均已迁入 `boss/` 子项目。
