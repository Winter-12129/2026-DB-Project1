# 基于 MongoDB 的问卷系统

这是一个基于 Flask + MongoDB 的在线问卷系统，支持题目跳转、匿名填写、重复提交控制和自动统计。

当前完成：用户账号、问卷创建管理、题目与条件跳转、公开填写、重复提交策略和统计结果。

## 已实现

- 题目库：支持直接新建题目、从问卷另存题目到题库，以及从题库选择版本加入问卷。
- 题目去重与别名：按规范化题干和内容指纹去重，相似表述可通过别名归入同一题目族。
- 题目共享：支持按用户名共享和取消共享；被共享用户可以使用题目，但不能修改原题目族。
- 版本管理：修改题目时可选择创建新版本或直接覆盖当前版本，并支持查看历史、恢复旧版本。
- 问卷快照：问卷保存题目副本和来源版本，题库修改不会影响已经完成或已经发布的问卷。
- 发布只读：已发布问卷禁止添加、删除或修改题目。
- 题目 ID 查询：支持用题目族 ID、版本 ID 或问卷内题目 ID 查询使用问卷和问卷 ID。
- 跨问卷统计：支持总体统计、分问卷统计和分版本统计；选择题显示选项比例，文本题显示高频答案，数字题显示平均值、中位数、标准差、分位数和区间分布。
- 权限隔离：跨问卷统计只汇总当前用户自己的问卷，避免共享题目后泄露其他用户的答卷。
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
| `question_bank/repository.py` | `question_bank` 集合的题目族、共享用户和版本读写 |
| `question_bank/service.py` | 去重、别名归并、版本创建与恢复、共享权限和来源快照 |
| `logic/service.py` | 跳转规则、路径求值、服务端路径重放 |
| `responses/repository.py` | `responses` 集合的答卷写入 |
| `responses/service.py` | 提交令牌、身份去重和答卷保存 |
| `analytics/repository.py` | 按问卷版本读取答卷 |
| `analytics/cross_survey_service.py` | 题目来源映射、跨问卷统计、分问卷和分版本分析 |
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

测试包括：

- 题目库直接建题、从问卷另存、题干去重、别名归并和跨问卷复用。
- 题目族共享、取消共享、被共享用户选题以及越权修改拦截。
- 创建新版本、直接覆盖、恢复旧版本、父版本关系和问卷快照隔离。
- 已发布问卷题目只读。
- 题目族 ID、版本 ID 和问卷内题目 ID 查询。
- 单选题、文本题和数字题的跨问卷统计、分问卷分析和分版本分析。
- 原问卷来源字段自动回填和使用问卷 ID 返回。
- MongoDB 题库 Validator、共享查询索引和题目使用问卷索引。
- 真实 Flask HTTP 全流程及 24 个单元测试。
## 当前边界

当前阶段不包含：

- 题目编辑和拖动排序（目前支持添加和删除）。
- 多条条件组合的图形化编辑器（数据结构支持 `clauses`，当前界面一次配置一个条件）。
- 跳转到页面或返回上一题。
- 图表、Excel 导出和文件上传。
- 答卷逐条删除和恢复。
- 跨问卷统计当前按需读取答卷；超大数据量时可进一步增加离线汇总集合。

公开链接现在可以真正填写；提交后答卷会写入 `responses` 集合，统计页会按当前问卷版本自动生成结果。

## 填写权限约定

- `allowAnonymous = true`：链接可以直接打开，不强制登录。
- `allowAnonymous = false`：未登录用户打开链接会先跳到登录页，登录成功后返回该链接。

这是对“是否允许匿名填写”和“填写者需要先登录”两条要求的组合实现。默认创建时不允许匿名，保证默认行为是必须登录。

## 目录

```text
项目仓库根目录/
  app.py
  config.py
  common/
  auth/
  surveys/
  questions/
  question_bank/
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
- `docs/13-question-bank.md`

完整提交清单见 `SUBMISSION.md`。
