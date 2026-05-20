---
name: job-buddy-agent
description: 使用 Job Buddy MCP 和本地简历材料，协助求职场景下的岗位筛选、职位评估、打招呼和聊天跟进。
---

# Job Buddy Agent Skill

这个 skill 主要服务求职场景，不直接替代 MCP 工具。
它的职责是指导 agent：

- 先读取本地简历与偏好文档
- 再通过 Job Buddy MCP 搜索和评估岗位
- 再决定是否生成或发送打招呼消息
- 再基于聊天记录判断下一步跟进动作

## 依赖

优先使用以下 MCP 工具：

- `auth_status`
- `search_jobs`
- `job_detail`
- `list_jobs`
- `chat_history`
- `send_message`
- `list_targets`
- `target_detail`

还需要读取以下本地材料：

- `references/my_resume.md`
- `references/job_preferences.md`
- `references/greeting_style.md`

## MCP 调用约束

- 所有 Job Buddy MCP 调用都必须串行执行，不能并发同时请求。
- 必须等待上一条 MCP 调用完成并拿到结果后，再决定是否发起下一条调用。
- 不要同时并发调用多个 `search_jobs`、`job_detail`、`chat_history`、`send_message`、`sync_friends`。
- 凡是可能触发 BOSS 页面操作、状态刷新或登录态依赖的调用，都按单线程工作流处理。

## 工作流

### 1. 开始前先建立上下文

在执行任何岗位推荐、筛选或打招呼操作前，先读取：

1. `references/my_resume.md`
2. `references/job_preferences.md`
3. `references/greeting_style.md`

如果这些文件缺失或内容明显不完整，先提醒操作者补齐，不要直接生成结论。

### 2. 找岗位

当用户说“帮我找岗位”“看看最近有什么职位”时：

1. 根据 `job_preferences.md` 整理搜索条件
2. 使用 `search_jobs`
3. 优先筛选：
   - 简历技能和经历能覆盖的岗位
   - 城市、薪资、经验要求符合偏好的岗位
   - `boss_active_text`、`boss_online`、`job_active_time` 更积极的岗位
4. 明确指出每个推荐岗位的匹配原因和风险点

### 3. 看详情

当用户要求评估某个岗位是否值得投时：

1. 使用 `job_detail`
2. 结合简历判断：
   - 技能匹配度
   - 职责匹配度
   - 经验跨度是否合理
   - 公司和岗位是否符合偏好
3. 输出结论时默认包含：
   - 推荐 / 谨慎 / 跳过
   - 匹配点
   - 风险点

### 4. 打招呼

当用户要求打招呼、生成招呼语或判断是否适合发首条消息时：

1. 先确认已经看过岗位详情
2. 结合 `my_resume.md` 和 `greeting_style.md` 生成个性化表达
3. 招呼语应突出：
   - 和岗位最相关的经历
   - 清晰的求职意图
   - 简短、专业、不过度热情
4. 默认先生成草稿，不擅自调用 `send_message`
5. 只有当用户明确要求发送，且已经有好友关系或聊天通道时，才调用 `send_message`

### 5. 聊天跟进

当用户要求“看看怎么回”“同步聊天”“下一步怎么跟进”时：

1. 使用 `chat_history`
2. 总结：
   - 对方当前态度
   - 当前进度阶段
   - 是否存在待回复问题
   - 下一步建议
3. 如需回复，先给回复草稿，再等用户明确确认后再发送

## 输出要求

- 推荐岗位时，说明“为什么匹配”
- 不推荐时，说明“为什么跳过”
- 生成招呼语时，必须能指出招呼语对应了简历中的哪一段能力或经历
- 对聊天回复草稿，保持简洁、职业、可直接发送

## 禁止事项

- 不要在没读简历和偏好前直接推荐岗位
- 不要把不匹配的岗位包装成“还不错”
- 不要在未经明确要求时直接发送消息
- 不要编造简历中不存在的经历或技能
