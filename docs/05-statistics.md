# 答卷保存、重复提交与统计

版本：0.1  
状态：已实现

## 1. 答卷文档

每次成功提交生成一个 `responses` 文档：

```json
{
  "_id": "ObjectId",
  "surveyId": "ObjectId",
  "surveyVersion": 1,
  "respondentId": "ObjectId 或 null",
  "anonymous": false,
  "participantKey": "user:xxx",
  "submissionToken": "本次提交唯一令牌",
  "submittedAt": "ISODate",
  "answers": [
    {"questionId": "q1", "type": "single_choice", "value": "o_a"},
    {"questionId": "q2", "type": "multiple_choice", "value": ["o_b"]},
    {"questionId": "q3", "type": "text", "value": "回答内容"},
    {"questionId": "q4", "type": "number", "value": 20}
  ],
  "visitedQuestionIds": ["q1", "q2", "q3", "q4"]
}
```

答卷不会追加到问卷文档中。这样多人同时填写时不会争抢同一份问卷文档，也不会触碰 MongoDB 单文档大小上限。

## 2. 重复提交策略

问卷字段：

```json
{
  "allowAnonymous": true,
  "allowMultipleResponses": false
}
```

- `allowMultipleResponses = true`：每次新 token 的提交都保存为新答卷。
- `allowMultipleResponses = false`：
  - 登录用户使用 `participantKey = "user:<用户ID>"`。
  - 匿名用户使用 `participantKey = "anon:<会话令牌哈希>"`。
  - 数据库部分唯一索引阻止同一身份重复提交。

匿名身份依赖签名会话 Cookie，因此只能是尽力限制；如果要求严格一人一份，应要求登录。

### `submissionToken`

公开填写页面生成一次 `submissionToken`，同一个 token 重复提交时返回已保存的答卷，避免双击或网络重试造成重复记录。

数据库索引：

```text
{ surveyId: 1, submissionToken: 1 } unique
partialFilterExpression: { submissionToken: { $type: "string" } }
```

同一身份限制索引：

```text
{ surveyId: 1, participantKey: 1 } unique
partialFilterExpression: { participantKey: { $type: "string" } }
```

当 `allowMultipleResponses = true` 时，`participantKey` 不参与唯一限制。

## 3. 统计来源

当前统计直接从 `responses` 集合读取当前问卷版本的全部已提交答卷，在 `analytics/service.py` 中自动计算。

不维护问卷文档中的累加计数器，避免多人同时提交时产生竞态和统计不一致。数据量增大后，可以增加可重建的统计缓存，但原始答卷仍然是事实来源。

统计只包含：

```text
surveyId = 当前问卷
surveyVersion = 当前问卷版本
```

这样问卷修改后不会把不同版本的题目混在一起。

## 4. 统计口径

### 单选题

- 每个选项的选择人数。
- `answeredCount`：实际回答该题的人数。
- `visitedCount`：访问过该题的人数。
- 未选择选项仍然返回 0。
- 选择率分母使用 `answeredCount`。

### 多选题

- 每个选项被选择的次数。
- 选择率分母使用回答了该题的人数。
- 因为一份答卷可以选择多个选项，选择率之和可能超过 100%。

### 文本题

- 返回所有文本答案，页面逐条展示。
- 额外识别可解析为数字的文本，返回数字数量、平均值、最小值、最大值。
- 非数字文本不进入平均值。

### 数字题

- 返回有效数字数量、平均值、最小值、最大值。
- 计算前使用 Decimal 转换，避免直接用浮点数比较。

## 5. 整卷与单题统计

```text
GET /surveys/<id>/stats
GET /surveys/<id>/stats?questionId=<qid>
```

整卷统计返回所有题目的统计；单题统计只返回指定题目，但仍然校验当前用户是问卷所有者。

## 6. 索引

`responses` 集合建议索引：

| 索引 | 用途 |
|---|---|
| `{ surveyId: 1, surveyVersion: 1, submittedAt: -1 }` | 按问卷版本读取答卷 |
| `{ surveyId: 1, "answers.questionId": 1 }` | 单题统计 |
| `{ surveyId: 1, "visitedQuestionIds": 1 }` | 访问人数统计 |
| `{ surveyId: 1, submissionToken: 1 }` unique partial | 防重复提交令牌 |
| `{ surveyId: 1, participantKey: 1 }` unique partial | 防同一身份重复填写 |

## 7. 当前边界

- 统计目前适合课程项目规模，采用应用层计算；以后可以迁移到 MongoDB 聚合或可重建的统计缓存。
- 暂不提供图表、Excel 导出和答卷逐条删除。
- 不允许匿名用户严格去重；严格场景请要求登录。
