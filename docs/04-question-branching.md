# 题目、条件跳转与公开填写

版本：0.1  
状态：已实现

## 1. 题目数据结构

题目和跳转规则内嵌在 `surveys` 文档中，不增加关系数据库表。

```json
{
  "id": "q_xxx",
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

题目 ID 和选项 ID 是稳定随机标识，不使用数组下标。跳转规则使用这些 ID。

四种题型：

| 类型 | `type` | 配置 |
|---|---|---|
| 单选 | `single_choice` | `options` |
| 多选 | `multiple_choice` | `options`、`config.minSelections`、`config.maxSelections` |
| 文本 | `text` | `config.minLength`、`config.maxLength` |
| 数字 | `number` | `config.min`、`config.max`、`config.integerOnly` |

必选由题目级字段 `required` 控制。只有实际访问到这道题时，必选才生效。

## 2. 跳转规则

规则保存在 `surveys.rules`：

```json
{
  "id": "r_xxx",
  "fromQuestionId": "q1",
  "priority": 1,
  "when": {
    "match": "all",
    "clauses": [
      {
        "questionId": "q1",
        "operator": "eq",
        "value": "o_a"
      }
    ]
  },
  "action": {
    "type": "jump",
    "targetQuestionId": "q5"
  }
}
```

当前界面支持：

- 单选：`eq`，选择某个选项。
- 多选：`includes_any` 或 `includes_all`。
- 数字：`eq`、`gt`、`gte`、`lt`、`lte`、`between`。
- 目标：后续题目，或结束问卷。

规则执行顺序：

1. 按 `priority` 从小到大检查。
2. 第一条匹配的规则生效。
3. 没有匹配规则时进入下一题。
4. 最后一题或 `end` 动作结束问卷。
5. 只允许跳到后面的题，避免循环。

同一道题不允许使用重复优先级。

## 3. 发布前校验

发布问卷时会检查：

- 至少有一道题。
- 题目 ID、选项 ID 唯一。
- 选项和配置合法。
- 跳转来源题和目标题存在。
- 目标题排在来源题之后。
- 条件引用的题目存在，且不能引用尚未回答的题。
- 操作符和题型兼容。
- 单选题、多选题条件引用有效选项。
- 数字条件范围合法。
- 同一来源题的优先级不重复。

校验失败时，问卷保持草稿状态。

## 4. 导航引擎

`logic/service.py` 提供：

- `next_step(document, current_question_id, answers)`：计算下一道题。
- `replay_path(document, answers)`：从起始题重新走完整路径。
- `validate_rules_for_publish(document)`：发布前规则校验。
- `rule_views(document)`：生成管理页的规则说明。

`questions/service.py` 提供：

- 题目添加和删除。
- 题型配置校验。
- 答案规范化和校验。
- 发布前题目检查。

## 5. 服务端路径重放

前端根据规则即时跳转，但提交时服务端不会相信前端传入的“路径”。服务端会：

1. 从 `startQuestionId` 开始。
2. 按最终答案逐题验证。
3. 只校验实际访问到的题目。
4. 丢弃访问路径之外的答案。
5. 记录服务端计算出的 `visitedQuestionIds`。

答卷文档示例：

```json
{
  "surveyId": "ObjectId",
  "surveyVersion": 1,
  "respondentId": "ObjectId/null",
  "anonymous": false,
  "participantKey": "user:xxx",
  "submissionToken": "本次提交唯一令牌",
  "submittedAt": "ISODate",
  "answers": [
    {"questionId": "q1", "type": "single_choice", "value": "o_a"}
  ],
  "visitedQuestionIds": ["q1", "q5"]
}
```

## 6. 公开填写流程

公开链接仍然是：

```text
/survey/<shareCode>
```

打开链接时：

- 不允许匿名的问卷：未登录用户先跳转登录，登录成功后返回原链接。
- 允许匿名的问卷：可以直接填写。
- 草稿链接不可公开访问。
- 已关闭或已截止的问卷只显示状态提示。

页面一次显示一道题。单选题选择后自动前进；多选、文本和数字题点击“下一题”继续。完成全部路径后显示提交按钮。

提交接口：

```text
POST /api/v1/surveys/<shareCode>/responses
```

请求体：

```json
{
  "answers": {
    "q1": "o_a",
    "q2": ["o_b", "o_c"],
    "q4": 20
  },
  "submissionToken": "本次提交唯一令牌"
}
```

## 7. 当前限制

- 题目暂不支持编辑和拖动排序，只能添加和删除。
- 规则界面一次配置一个条件；数据结构的 `clauses` 已为多条件组合预留。
- 不支持返回上一题后自动清理下游答案；当前流程按向前导航设计。
- 重复提交策略由问卷的 `allowMultipleResponses` 控制。
- 题目级统计见 `05-statistics.md`；图表和导出尚未实现。
