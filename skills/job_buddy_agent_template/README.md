# Job Buddy Agent Template

这是 Job Buddy 的通用 skill 模板，用来快速生成本地私有版本。

模板本身可以提交到 git。
真实的个人简历、个人求职偏好和个人打招呼风格，不应直接写在模板里。

## 使用方式

运行：

```bash
uv run python scripts/setup_skill.py
```

脚本会在仓库内生成一个被 `.gitignore` 忽略的私有目录：

```text
skills-local/job_buddy_agent/
```

生成后请补齐：

- `references/my_resume.md`
- `references/job_preferences.md`
- `references/greeting_style.md`
