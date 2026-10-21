# 基于 MongoDB 的问卷系统

这是一个基于 Flask + MongoDB 的在线问卷系统，支持题目跳转、匿名填写、重复提交控制和自动统计。

当前完成：用户账号、问卷创建管理、题目与条件跳转、公开填写、重复提交策略和统计结果。

## 已实现

- 账号与权限：支持注册、登录、退出；用户只能查看和管理自己创建的问卷。
- 问卷管理：创建问卷、填写标题和说明、设置匿名与重复填写策略；支持发布、截止时间、关闭和分享链接。
- 题目管理：支持单选、多选、文本、数字题；可设置必填、多选数量、文本字数、数字范围和整数限制。
- 条件跳转：可为单选、多选和数字题配置跳转规则，按优先级执行；服务端提交时重新计算访问路径。
- 填写提交：公开链接逐题作答、自动跳转；提交令牌保证双击和重试幂等，并按问卷策略限制重复填写。
- 统计结果：支持整卷和单题统计，包括单选人数、多选次数、文本内容、数字平均值及最值。

## 用户数据

`users` 集合中的用户文档至少包含：

| 字段 | 含义 |
|---|---|
| `_id` | MongoDB 自动生成的用户 ID |
| `username` | 用户名，唯一 |
| `passwordHash` | 密码哈希，不保存明文密码 |
| `createdAt` | 注册时间，UTC |

## 数据库接口放在哪里

| 文件 | 负责的数据 |
|---|---|
| `common/db.py` | MongoDB 连接、集合入口和索引 |
| `auth/repository.py` | `users` 集合的插入和查询 |
| `surveys/repository.py` | `surveys` 集合的创建、按所有者查询、按 ID 查询、按分享码查询、状态和截止时间更新 |
| `publishing/service.py` | 发布、设置截止时间、关闭、公开访问状态判断 |
| `questions/service.py` | 题目的添加、删除、答案校验和发布前检查 |
| `logic/service.py` | 跳转规则、路径求值、服务端路径重放 |
| `responses/repository.py` | `responses` 集合的答卷写入 |
| `responses/service.py` | 提交令牌、身份去重和答卷保存 |
| `analytics/repository.py` | 按问卷版本读取答卷 |
| `analytics/service.py` | 整卷和单题统计计算 |

业务代码不直接写 MongoDB 查询，而是调用对应模块的 repository。

## 运行

先确认 MongoDB 已经启动。然后在本项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:SECRET_KEY = "请换成一个随机字符串"
$env:MONGO_URI = "mongodb://127.0.0.1:27017"
$env:MONGO_DB_NAME = "survey_system"

.\.venv\Scripts\python.exe app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

如果已经有可用的全局 Flask 和 PyMongo，也可以直接从第三步的环境变量开始，用 `python app.py` 运行。

## 测试

测试使用内存中的数据库替身，不要求本机 MongoDB 正在运行：

```powershell
python -m unittest discover -s tests -v
```

HTTP 集成测试需要 `requests`，它列在 `requirements-dev.txt` 中。具体启动方式见 `docs/06-测试案例与结果.md`。

测试覆盖：

- 账号与权限：注册、登录、密码哈希、用户名唯一索引，以及用户只能管理自己的问卷和统计。
- 问卷生命周期：创建、发布、截止、关闭、分享码和公开链接；空问卷禁止发布。
- 填写权限：非匿名问卷跳转登录，登录后返回原链接；匿名问卷可直接填写。
- 题目与跳转：四类题型及其限制校验；单选、多选、数字题跳转；被跳过的必填题不阻塞提交，服务端重放路径并丢弃未访问题目的答案。
- 答卷提交：保存 `visitedQuestionIds`；同一 `submissionToken` 幂等；按问卷设置限制同一身份重复提交，允许时保存多份答卷。
- 统计结果：覆盖单选、多选、文本和数字题，并支持整卷统计和单题统计。

## 当前边界

当前阶段不包含：

- 题目编辑和拖动排序（目前支持添加和删除）。
- 多条条件组合的图形化编辑器（数据结构支持 `clauses`，当前界面一次配置一个条件）。
- 跳转到页面或返回上一题。
- 图表、Excel 导出和文件上传。
- 答卷逐条删除和恢复。

公开链接现在可以真正填写；提交后答卷会写入 `responses` 集合，统计页会按当前问卷版本自动生成结果。

## 填写权限约定

- `allowAnonymous = true`：链接可以直接打开，不强制登录。
- `allowAnonymous = false`：未登录用户打开链接会先跳到登录页，登录成功后返回该链接。

这是对“是否允许匿名填写”和“填写者需要先登录”两条要求的组合实现。默认创建时不允许匿名，保证默认行为是必须登录。

## 目录

```text
survey-system/
  app.py
  config.py
  common/
  auth/
  surveys/
  questions/
  logic/
  publishing/
  responses/
  analytics/
  templates/
  static/
  tests/
  docs/
```

设计文档：

- `docs/01-system-design.md`
- `docs/02-auth-feature.md`
- `docs/03-survey-management.md`
- `docs/04-question-branching.md`
- `docs/05-statistics.md`
- `docs/06-测试案例与结果.md`
- `docs/07-系统设计与提交说明.md`
- `docs/08-MongoDB-Schema.md`
- `docs/09-配置说明.md`
- `docs/10-项目完成报告.md`
- `docs/11-AI使用日志.md`
- `docs/12-查询与索引证据.md`

完整提交清单见 `SUBMISSION.md`。
