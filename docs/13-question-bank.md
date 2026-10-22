# 第二阶段功能：题目库与版本

## 1. 设计目标

用户可以直接在题目库新建常用题，也可以在问卷中勾选“同时保存到题目库”。之后可以从题目库选择任意版本加入新问卷，同一道库题目可以被多份问卷使用。

问卷中的题目保存的是快照：

```text
题目库保存可复用题目和版本历史
        ↓ 选择时复制快照
问卷 questions[] 保存自己的题目副本
```

这样题库产生新版本时，不会悄悄改变已经发布的问卷和旧答卷。

## 2. 两层数据模型

题库使用“题目族 → 版本”两层结构，不再保留单独的变体层：

```text
question_bank
├─ ownerId
├─ familyKey          规范化后的题干族键
├─ title              题目族展示名
├─ aliases[]          人工维护的别名
├─ aliasKeys[]        规范化别名
├─ sharedWith[]       被共享用户 ObjectId
├─ currentVersionId   当前默认版本
└─ versions[]         版本快照
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

修改题干、题型、选项或配置时有两种保存方式：创建新版本时旧版本永久保留；直接修改时覆盖所选版本。`parentVersionId` 说明新版本由哪个旧版本修改而来。无论采用哪种方式，已经加入问卷的题目快照都不会改变。

## 3. 去重规则

题目族使用规范化题干匹配：

```text
trim
→ Unicode NFKC
→ 转小写
→ 去除空白和标点
```

版本指纹使用：

```text
type + 选项 label 列表 + config
```

不使用选项 ID 参与指纹，因为同一道题在不同问卷中重新生成选项 ID 不应被视为新内容。

相同规范化题干会进入同一题目族；即使内容不同，也只追加版本，不重复创建题目族。

“姓名”和“你的名字是”这类相似但不完全相同的题干不会自动模糊合并；用户可以在题目库页面添加别名，让后续保存归入同一题目族。

## 4. 版本关系

- `parentVersionId`：新版本从哪个版本修改而来。
- `currentVersionId`：当前默认版本；恢复操作只切换这个指针，不覆盖或删除任何版本。
- 版本列表按 `number` 倒序展示，最新版本在前，当前版本加标记。

恢复流程：

```text
当前 v3
→ 先保存当前编辑内容为 v4（如果存在未保存修改）
→ 将 currentVersionId 指向旧版本 v1
→ v1 成为当前使用版本
→ v2、v3、v4 仍保留在历史中
```

问卷选择任意版本时，都复制该版本完整内容作为快照，并记录 `sourceBankId`、`sourceVersionId`。

## 5. 接口和页面

| 路径 | 作用 |
|---|---|
| `GET /question-bank` | 查看题目族、版本历史和共享题目 |
| `GET/POST /question-bank/new` | 直接创建常用题目 |
| `GET /question-bank/lookup` | 按题目族 ID、版本 ID 或问卷内题目 ID 查询 |
| `GET /question-bank/insights/<题目ID>` | 使用问卷和跨问卷分析页面 |
| `GET /api/v1/question-bank/insights/<题目ID>` | 跨问卷分析 JSON |
| `POST /question-bank/<familyId>/aliases` | 添加题目别名 |
| `POST /question-bank/<familyId>/share` | 按用户名共享 |
| `POST /question-bank/<familyId>/unshare` | 取消共享 |
| `POST /question-bank/<familyId>/delete` | 删除自己的题目族 |
| `GET/POST /question-bank/<familyId>/versions/new` | 基于旧版本创建新版本 |
| `POST /question-bank/<familyId>/versions/<versionId>/restore` | 切换当前版本 |
| `POST /surveys/<surveyId>/questions/from-bank` | 从题库选择任意版本加入问卷 |

问卷题目会保存来源快照：

```json
{
  "sourceBankId": "ObjectId 字符串",
  "sourceVersionId": "ver_xxx"
}
```

## 6. 题目 ID 查询与跨问卷统计

题库支持三种查询参数：

- 题目族 ObjectId：统计该题目族的所有版本。
- `ver_...`：只统计指定版本。
- `q_...`：通过问卷内题目 ID 定位来源版本。

系统通过 `sourceBankId + sourceVersionId` 找到使用该题目的问卷，再使用每份问卷自己的本地题目 ID 从 `responses.answers` 读取答案。查询结果会返回问卷 ID、问卷标题、状态、使用版本、本地题目 ID、提交数、访问数、回答数和回答率。

总体分析按题型生成：

- 单选题：选项次数、回答者比例和分布。
- 多选题：各选项次数、总选择次数和人均选择数。
- 数字题：平均值、中位数、标准差、最小/最大、分位数和区间直方图。
- 文本题：答案数、不同内容数、长度、高频答案、全部文本和可识别数字分析。

统计同时包含：

- 每份问卷的独立答题分布。
- 每个版本的问卷数、使用记录、访问数和回答数。
- 跨版本合并后的总体分布。

跨问卷统计只查询当前用户自己的问卷。共享题目让他人使用时，不会因此让题目所有者看到其他用户问卷中的答卷数据。

## 7. 共享规则

题目族增加 `sharedWith` 用户 ID 数组。所有者可以在题目库页面输入另一个用户名进行共享，也可以取消共享。

- 所有者继续拥有题目族，可以编辑别名、共享和删除。
- 被共享用户可以在“共享给我的题目”区域查看题目族和版本历史。
- 被共享用户可以在自己的草稿问卷中使用任意版本，系统仍然复制题目快照。
- 被共享用户不能修改原题目族、创建新版本、恢复版本或删除题目族。
- 取消共享后，后续不能再使用；已经复制到问卷中的快照不受影响。

这里共享的是题目定义，不是问卷和答卷数据。共享关系使用用户 ObjectId，不复制整份题库文档到每个用户。

## 8. 索引与校验

```text
{ ownerId: 1, familyKey: 1 } unique
{ ownerId: 1, aliasKeys: 1 }
{ sharedWith: 1, updatedAt: -1 }
```

问卷集合使用多键索引：

```text
{ ownerId: 1, questions.sourceBankId: 1 }
```

MongoDB Validator 要求题目族包含用户、标题、别名、共享用户、当前版本和时间字段；`versions[]` 至少有一个元素，每个版本包含完整题干、题型、选项、配置、版本号、父版本和创建时间。缺少 `versions` 的文档会被拒绝。

## 9. 当前边界

- 批量共享暂不提供界面，可后续通过批量选择用户实现。
- 不支持自动语义相似度合并；相似题干通过别名人工归并。
- 不支持题库批量导入。
- 已发布问卷仍然只读，题库新版本或覆盖修改都不会改变已有问卷快照。
- 跨问卷统计按需读取答卷，适合课程项目规模；大规模数据可再增加离线汇总。