# Workflow Examples

## 场景 1：找新岗位

1. 读取 `my_resume.md`
2. 读取 `job_preferences.md`
3. 调用 `search_jobs`
4. 结合匹配度输出推荐列表

## 场景 2：评估职位是否值得投

1. 读取 `my_resume.md`
2. 调用 `job_detail`
3. 输出匹配点与风险点

## 场景 3：生成打招呼草稿

1. 读取 `my_resume.md`
2. 读取 `greeting_style.md`
3. 调用 `job_detail`
4. 生成草稿，默认不直接发送
