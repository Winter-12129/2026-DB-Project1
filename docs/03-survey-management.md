# 第一阶段功能 2：问卷创建与管理

版本：0.1  
状态：问卷管理阶段设计说明（题目和填写见 `04-question-branching.md`）

> 题目、条件跳转和公开填写已在 `04-question-branching.md` 中实现；本文保留问卷管理阶段的设计说明。

## 1. 功能范围

本功能实现：

- 创建问卷。
- 填写问卷标题。
- 填写问卷说明。
- 设置是否允许匿名填写。
- 查看当前用户创建的问卷列表。
- 发布问卷。
- 设置问卷截止时间。
- 关闭问卷。
- 为每份问卷生成分享链接。
- 打开公开链接时执行登录和访问状态检查。

当前不实现：

- 题目编辑。
- 条件显示和跳转。
- 正式答卷提交。
- 题目级统计。

## 2. 数据组织方式

所有问卷放在一个 MongoDB 集合 `surveys` 中。用户不通过关系数据库外键或联表查询关联，而是在问卷文档里保存创建者的 ObjectId：

```text
users._id  ←  surveys.ownerId
```

应用层使用 `ownerId` 过滤问卷，不使用 SQL 外键、JOIN 或关系型数据库。

`surveys` 文档的主要字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | 问卷 ID |
| `ownerId` | ObjectId | 创建者用户 ID |
| `title` | string | 问卷标题 |
| `description` | string | 问卷说明 |
| `allowAnonymous` | boolean | 是否允许匿名填写 |
| `allowMultipleResponses` | boolean | 是否允许同一身份重复填写 |
| `shareCode` | string | 分享码，唯一索引 |
| `status` | string | `draft`、`published`、`closed` |
| `deadline` | datetime/null | 截止时间，UTC |
| `publishedAt` | datetime/null | 发布时间，UTC |
| `closedAt` | datetime/null | 关闭时间，UTC |
| `createdAt` | datetime | 创建时间，UTC |
| `updatedAt` | datetime | 最后更新时间，UTC |

## 3. 分享码和链接

分享码在创建问卷时生成，使用随机字母和数字组成，长度为 10：

```text
/survey/<shareCode>
```

示例：

```text
/survey/k7m3pq9xab
```

设计要点：

- 分享码存放在问卷文档中，不依赖数组下标或可预测的 ObjectId。
- `shareCode` 建立唯一索引，避免两个问卷使用同一个链接。
- 生成后保持稳定，方便用户复制和分发。
- 草稿阶段链接不可公开访问；发布后才能打开。
- 截止或关闭后，链接仍然存在，但显示截止或关闭提示。

## 4. 状态和截止时间

状态转换：

```text
草稿 draft
  │ 发布
  ▼
已发布 published
  │ 关闭
  ▼
已关闭 closed
```

规则：

- 只有草稿可以发布。
- 只有已发布问卷可以关闭。
- 已关闭问卷不能再次发布。
- 截止时间是已发布问卷的有效期；超过截止时间后，即使状态仍是 `published`，也不能继续填写。
- 截止时间按上海时区输入，保存前转换为 UTC。
- 截止时间必须晚于当前时间。

## 5. 填写权限规则

默认创建时 `allowAnonymous = false`，即填写者必须先登录。

- `allowAnonymous = false`：未登录用户打开 `/survey/<shareCode>`，跳转到登录页，并在登录成功后返回原链接。
- `allowAnonymous = true`：链接可以直接打开，不强制登录；已登录用户仍会显示当前账号。
- 已关闭或已截止的问卷，打开链接只显示状态提示，不要求登录。

这是对“是否允许匿名填写”和“填写者需要先登录”两条要求的组合实现：默认必须登录，开启匿名后才允许匿名访问。

## 6. 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/surveys` | 当前用户的问卷列表 |
| GET | `/surveys/<id>` | 问卷管理页 |
| GET/POST | `/surveys/new` | 创建问卷 |
| POST | `/surveys/<id>/publish` | 发布问卷 |
| POST | `/surveys/<id>/deadline` | 设置截止时间 |
| POST | `/surveys/<id>/close` | 关闭问卷 |
| GET | `/survey/<shareCode>` | 公开访问链接 |

管理类接口全部要求登录，并校验当前用户是问卷所有者。公开链接只读取已发布或已关闭问卷，不暴露所有者管理接口。

## 7. 数据库接口

| 文件 | 职责 |
|---|---|
| `common/db.py` | MongoDB 连接、`shareCode` 唯一索引、用户和问卷查询索引 |
| `common/ids.py` | 生成随机分享码 |
| `common/time_utils.py` | UTC、上海时区转换和截止时间解析 |
| `surveys/repository.py` | 创建、按所有者查询、按 ID 查询、按分享码查询、更新状态和截止时间 |
| `publishing/service.py` | 发布、截止时间、关闭和公开访问状态判断 |
| `publishing/routes.py` | 管理动作和公开链接路由 |

业务层不直接操作 MongoDB 集合；问卷的数据库读写集中在 `surveys/repository.py`。

## 8. 测试覆盖

`tests/test_first_feature.py` 覆盖：

- 创建问卷时保存标题、说明、匿名策略和分享码。
- 管理页显示分享链接。
- 发布问卷。
- 设置截止时间。
- 关闭问卷。
- 草稿链接不可公开访问。
- 非匿名问卷跳转登录，登录后返回原链接。
- 匿名问卷无需登录即可打开。
- 其他用户不能管理或发布问卷。

## 9. 下一步

1. 在问卷文档中增加题目数组，由题目模块维护。
2. 为公开链接页面接入题目渲染和答案提交。
3. 将答卷记录到 `responses` 集合，并保留问卷版本。
4. 在 `analytics/repository.py` 中增加题目级聚合。
