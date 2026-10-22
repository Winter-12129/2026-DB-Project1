# MongoDB Schema

本文档对应当前第二阶段代码。MongoDB 的实际读写位于各模块的 `repository.py`，索引创建位于 `common/db.py`。

## 1. 集合关系

系统使用四个业务集合：

| 集合 | 作用 |
|---|---|
| `users` | 用户账号 |
| `surveys` | 问卷定义、题目、选项和跳转规则 |
| `responses` | 每次提交的答卷 |
| `question_bank` | 题目族、别名、共享用户和版本历史 |

```text
users._id
   ├─ ownerId → surveys
   └─ ownerId → question_bank

surveys
   ├─ surveyId → responses
   └─ sourceBankId / sourceVersionId → question_bank 的所选版本
```

`ownerId` 和 `surveyId` 是 MongoDB 文档引用。系统不使用关系数据库外键，也不在运行代码中执行 SQL JOIN。

## 2. users

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | ObjectId | 是 | 用户 ID |
| `username` | String | 是 | 用户名 |
| `passwordHash` | String | 是 | 密码哈希 |
| `createdAt` | Date | 是 | 注册时间，UTC |

示例：

```json
{
  "_id": "ObjectId(...)",
  "username": "alice",
  "passwordHash": "scrypt:...",
  "createdAt": "ISODate(...)"
}
```

唯一索引：

```text
{ username: 1 } unique
```

## 3. surveys

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | ObjectId | 是 | 问卷 ID |
| `ownerId` | ObjectId | 是 | 创建者用户 ID |
| `title` | String | 是 | 标题 |
| `description` | String | 否 | 说明 |
| `allowAnonymous` | Boolean | 是 | 是否允许匿名 |
| `allowMultipleResponses` | Boolean | 是 | 是否允许同一身份多次提交 |
| `shareCode` | String | 是 | 分享码 |
| `status` | String | 是 | `draft`、`published`、`closed` |
| `version` | Int32 | 是 | 问卷内容版本 |
| `schemaVersion` | Int32 | 是 | 文档结构版本 |
| `startQuestionId` | String/null | 否 | 起始题 |
| `questions` | Array | 是 | 题目数组 |
| `rules` | Array | 是 | 跳转规则数组 |
| `deadline` | Date/null | 否 | 截止时间 |
| `publishedAt` | Date/null | 否 | 发布时间 |
| `closedAt` | Date/null | 否 | 关闭时间 |
| `createdAt` | Date | 是 | 创建时间 |
| `updatedAt` | Date | 是 | 更新时间 |

### 3.1 questions 嵌套字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String | 题目稳定 ID |
| `order` | Int32 | 默认顺序 |
| `type` | String | `single_choice`、`multiple_choice`、`text`、`number` |
| `title` | String | 题干 |
| `required` | Boolean | 是否必选 |
| `options` | Array | 单选题、多选题的选项 |
| `config` | Object | 多选数量、文本长度、数字范围等配置 |
| `sourceBankId` | String | 来源题目族 ID，可选 |
| `sourceVersionId` | String | 来源题库版本 ID，可选 |

选项：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String | 选项稳定 ID |
| `label` | String | 显示文字 |

示例：

```json
{
  "id": "q_example",
  "order": 1,
  "type": "single_choice",
  "title": "请选择",
  "required": true,
  "options": [
    {"id": "o_a", "label": "A"},
    {"id": "o_b", "label": "B"}
  ],
  "config": {}
}
```

### 3.2 rules 嵌套字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String | 规则稳定 ID |
| `fromQuestionId` | String | 触发规则的题 |
| `priority` | Int32 | 同一来源题的优先级 |
| `when` | Object | 条件 |
| `action` | Object | 跳转或结束 |

`when.clauses` 是条件数组：

| 字段 | 类型 | 说明 |
|---|---|---|
| `questionId` | String | 条件读取哪道题的答案 |
| `operator` | String | `eq`、`includes_any`、`includes_all`、`between` 等 |
| `value` | 任意 | 单值条件 |
| `values` | Array | 多选条件 |
| `min` / `max` | Number | 数值区间 |

示例：

```json
{
  "id": "r_example",
  "fromQuestionId": "q1",
  "priority": 1,
  "when": {
    "match": "all",
    "clauses": [
      {"questionId": "q1", "operator": "eq", "value": "o_a"}
    ]
  },
  "action": {
    "type": "jump",
    "targetQuestionId": "q4"
  }
}
```

## 4. responses

| 字段 | BSON 类型 | 必填 | 说明 |
|---|---|---|---|
| `_id` | ObjectId | 是 | 答卷 ID |
| `surveyId` | ObjectId | 是 | 问卷 ID |
| `surveyVersion` | Int32 | 是 | 提交时版本 |
| `respondentId` | ObjectId/null | 否 | 登录用户 |
| `anonymous` | Boolean | 是 | 是否匿名 |
| `participantKey` | String/null | 否 | 同一身份限制键 |
| `submissionToken` | String | 是 | 提交幂等键 |
| `submittedAt` | Date | 是 | 提交时间 |
| `answers` | Array | 是 | 规范化答案 |
| `visitedQuestionIds` | Array | 是 | 服务端计算的访问路径 |

答案嵌套字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `questionId` | String | 题目 ID |
| `type` | String | 题型 |
| `value` | String/Array/Number | 单选为字符串，多选为数组，数字为数字 |

示例：

```json
{
  "surveyId": "ObjectId(...)",
  "surveyVersion": 1,
  "respondentId": "ObjectId(...)",
  "anonymous": false,
  "participantKey": "user:...",
  "submissionToken": "uuid-or-random",
  "submittedAt": "ISODate(...)",
  "answers": [
    {"questionId": "q1", "type": "single_choice", "value": "o_a"},
    {"questionId": "q2", "type": "multiple_choice", "value": ["o_b"]},
    {"questionId": "q4", "type": "number", "value": 20}
  ],
  "visitedQuestionIds": ["q1", "q2", "q4"]
}
```

## 5. 索引

| 集合 | 索引 | 选项 |
|---|---|---|
| `users` | `{ username: 1 }` | unique |
| `surveys` | `{ shareCode: 1 }` | unique, sparse |
| `surveys` | `{ ownerId: 1, createdAt: -1 }` | 普通 |
| `responses` | `{ surveyId: 1, submittedAt: -1 }` | 普通 |
| `responses` | `{ surveyId: 1, surveyVersion: 1, submittedAt: -1 }` | 普通 |
| `responses` | `{ surveyId: 1, submissionToken: 1 }` | unique, partial |
| `responses` | `{ surveyId: 1, participantKey: 1 }` | unique, partial |
| `responses` | `{ surveyId: 1, answers.questionId: 1 }` | 普通 |
| `responses` | `{ surveyId: 1, visitedQuestionIds: 1 }` | 普通 |
| `question_bank` | `{ ownerId: 1, familyKey: 1 }` | unique |
| `question_bank` | `{ ownerId: 1, aliasKeys: 1 }` | 普通 |
| `question_bank` | `{ sharedWith: 1, updatedAt: -1 }` | 普通 |
| `surveys` | `{ ownerId: 1, questions.sourceBankId: 1 }` | 普通，多键索引 |

`participantKey` 和 `submissionToken` 使用部分索引，只对字段存在且为字符串的文档生效。

## 6. 设计约束

- 题目、选项和规则使用稳定 ID，不使用数组下标。
- 题目和规则内嵌在问卷中；答卷单独保存。
- 发布时至少有一道题；规则目标必须是当前题之后的题。
- 答案只保存规范化后的值；选项文字以问卷定义为准。
- 统计按 `surveyVersion` 过滤，不混用不同版本。
- 跨问卷统计使用问卷题目中的 `sourceBankId` 和 `sourceVersionId` 定位题库来源。
- `allowMultipleResponses=true` 时不写 `participantKey`，允许同一身份多份答卷。
- `submissionToken` 重复请求返回已有答卷，不新增记录。

## 7. 代码位置

| 内容 | 文件 |
|---|---|
| 数据库连接和索引 | `common/db.py` |
| 用户文档 | `auth/repository.py` |
| 问卷文档 | `surveys/repository.py` |
| 答卷文档 | `responses/repository.py` |
| 题目库文档 | `question_bank/repository.py` |
| 字段校验 | `questions/service.py`、`logic/service.py`、`question_bank/service.py` |
| 统计读取 | `analytics/repository.py` |

## 8. 数据库级 Validator

`common/schema.py` 为四个集合定义 `$jsonSchema` 校验器，`common/db.py` 在应用启动时应用：

- `users`：用户名、密码哈希和注册时间。
- `surveys`：状态枚举、题目和规则数组、时间字段。
- `responses`：问卷 ID、版本、提交令牌、答案数组和访问路径。
- `question_bank`：题目族、别名、共享用户和完整版本历史。

校验使用 `validationLevel: moderate` 和 `validationAction: error`。已有历史文档保留，新的非法写入会被 MongoDB 拒绝。实际拒绝记录和 explain 结果见 `docs/12-查询与索引证据.md`。

## 9. question_bank

题目库使用“题目族 → 版本”的两层结构：

```text
question_bank
├─ ownerId
├─ familyKey
├─ title
├─ aliases[] / aliasKeys[]
├─ sharedWith[]         被共享用户的 ObjectId
├─ currentVersionId
└─ versions[]
   ├─ id
   ├─ number
   ├─ fingerprint
   ├─ title
   ├─ type
   ├─ options[]
   ├─ config{}
   ├─ parentVersionId
   └─ createdAt
```

唯一索引：

```text
{ ownerId: 1, familyKey: 1 } unique
```

辅助索引：

```text
{ ownerId: 1, aliasKeys: 1 }
```

共享查询索引：

```text
{ sharedWith: 1, updatedAt: -1 }
```

题目族按规范化题干匹配。用户可以直接在题目库新建题目，也可以在问卷中勾选“同时保存到题目库”。编辑时可以选择创建新版本，或覆盖所选版本；覆盖只改变题库版本，不修改已经保存到问卷的题目快照。`currentVersionId` 表示当前默认版本，其他版本仍可被问卷选择。问卷选择题目时复制快照，并记录 `sourceBankId`、`sourceVersionId`；从问卷另存到题库时，系统也会把来源字段回填到原问卷题目。

跨问卷统计不需要新增“总统计表”。系统先通过 `{ ownerId, questions.sourceBankId }` 索引找到候选问卷，再根据每题快照中的来源 ID 和问卷本地题目 ID 读取 `responses.answers`。分问卷、分版本和总体结果按需计算，避免维护容易失真的跨卷计数器。
