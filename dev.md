## 您的环境存在异常

搜索页连续请求5次就会触发。

## 用户需求
1. 自动化的投简历并跟进情况。
2. 有一个管理后台，配置一些参数。
3. 要有历史的数据记录。
4. 飞书上要能得到通知

## 页面原型
不考虑


## 数据结构
不考虑

## 业务梳理
不考虑
先快速出手，后期在迭代。



### boss网站操作：

BossClient:
实际对boss直聘网站的操作。
不涉及数据库操作。


| function       | schema-in | schema-out | note |
|----------------|-----------|------------|------|
| login          | LoginIn   | LoginOut   | ---  |
| getLoginStatus | LoginIn   | LoginOut   | ---  |
| logout         | LoginIn   | LoginOut   | ---  |
| searchJob      | LoginIn   | LoginOut   | ---  |
| getJobDetail   | LoginIn   | LoginOut   | ---  |
| getFriendList  | LoginIn   | LoginOut   | ---  |
| greet          | LoginIn   | LoginOut   | ---  |
| getChatHistory | LoginIn   | LoginOut   | ---  |
| sendMessage    | LoginIn   | LoginOut   | ---  |

#


## 路由梳理

### API 主入口

| 前缀          | 说明                                             | 代码位置                            |
|-------------|------------------------------------------------|---------------------------------|
| `/boss`     | BOSS 业务接口，包括 jobs/tasks/workers/friends/system | `src/job_buddy/routers/boss.py` |
| `/web`      | 站内管理接口，包括 health/dashboard/targets/system      | `src/job_buddy/routers/web.py`  |
| `/`         | 前端首页，返回 SPA 页面                                 | `src/job_buddy/web/app.py`      |
| `/assets/*` | 前端静态资源                                         | `src/job_buddy/web/app.py`      |

### `/boss` 路由

| Method | Path                                             | 说明                                       |
|--------|--------------------------------------------------|------------------------------------------|
| `GET`  | `/boss/jobs`                                     | 职位列表，支持 `match_status`、`greeted`、`limit` |
| `GET`  | `/boss/jobs/{source_job_id}/detail`              | 职位详情，支持 `security_id`、`force_refresh`    |
| `POST` | `/boss/jobs/search`                              | 只读职位搜索，不落库                               |
| `GET`  | `/boss/jobs/collections`                         | 采集记录列表                                   |
| `POST` | `/boss/tasks/search`                             | 触发搜索任务                                   |
| `POST` | `/boss/tasks/greet`                              | 触发打招呼任务                                  |
| `GET`  | `/boss/tasks`                                    | 任务列表                                     |
| `GET`  | `/boss/tasks/{task_id}`                          | 任务详情和记录                                  |
| `GET`  | `/boss/workers`                                  | 返回 `search`、`detail` 两个 worker 配置        |
| `GET`  | `/boss/workers/{worker_name}`                    | 获取单个 worker 配置                           |
| `PUT`  | `/boss/workers/{worker_name}`                    | 更新单个 worker 配置                           |
| `POST` | `/boss/workers/{worker_name}/start`              | 启动 worker                                |
| `POST` | `/boss/workers/{worker_name}/stop`               | 停止 worker                                |
| `GET`  | `/boss/friends`                                  | 好友列表                                     |
| `POST` | `/boss/friends/sync`                             | 同步好友                                     |
| `GET`  | `/boss/friends/{source_friend_id}/messages`      | 好友消息列表                                   |
| `POST` | `/boss/friends/{source_friend_id}/messages/send` | 发送好友消息                                   |
| `GET`  | `/boss/system/doctor`                            | 运行系统诊断                                   |
| `GET`  | `/boss/system/auth`                              | 获取登录状态                                   |
| `POST` | `/boss/system/auth/login`                        | 发起登录                                     |
| `POST` | `/boss/system/auth/logout`                       | 登出                                       |

### `/web` 路由

| Method   | Path                         | 说明       |
|----------|------------------------------|----------|
| `GET`    | `/web/health`                | 健康检查     |
| `GET`    | `/web/dashboard`             | 仪表盘摘要    |
| `GET`    | `/web/targets`               | 目标列表     |
| `POST`   | `/web/targets`               | 创建目标     |
| `GET`    | `/web/targets/{target_id}`   | 目标详情     |
| `PUT`    | `/web/targets/{target_id}`   | 更新目标     |
| `DELETE` | `/web/targets/{target_id}`   | 删除目标     |
| `GET`    | `/web/system/search-options` | 获取搜索选项枚举 |
| `GET`    | `/web/system/logs`           | 获取系统日志   |
| `POST`   | `/web/system/data/clear`     | 清空业务数据   |

### 备注

| 项目        | 内容                                                     |
|-----------|--------------------------------------------------------|
| Worker 名称 | 当前仅支持 `search` 和 `detail`                              |
| SPA 回退    | 非 `/boss`、`/web`、`/docs`、`/openapi.json` 的未知路径会回退到前端页面 |
