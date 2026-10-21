# 第一阶段功能 1：用户账号与问卷归属

版本：0.1  
状态：已实现，待接入题目与答卷模块

## 1. 功能范围

本功能实现：

- 注册账号。
- 登录、退出。
- 使用当前登录账号创建问卷草稿。
- 查看当前账号创建的问卷列表。
- 进入自己问卷的统计页，读取答卷数量。

本功能不实现：

- 题目编辑。
- 条件显示和跳转。
- 发布和分享链接。
- 填写问卷。
- 题目级统计和图表。

## 2. 页面与路由

| 方法 | 路径 | 作用 | 登录要求 |
|---|---|---|---|
| GET/POST | `/register` | 注册账号 | 否 |
| GET/POST | `/login` | 登录 | 否 |
| POST | `/logout` | 退出登录 | 是 |
| GET | `/surveys` | 查看当前用户的问卷列表 | 是 |
| GET/POST | `/surveys/new` | 创建问卷 | 是 |
| GET | `/surveys/<id>/stats` | 查看问卷统计 | 是，且必须是所有者 |

## 3. 数据库集合

### 3.1 `users`

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | 用户 ID |
| `username` | string | 用户名，唯一索引 |
| `passwordHash` | string | 密码哈希，不保存明文密码 |
| `createdAt` | datetime | 注册时间，UTC |

### 3.2 `surveys`

第一阶段只保存问卷基本信息和归属关系：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | ObjectId | 问卷 ID |
| `ownerId` | ObjectId | 创建者用户 ID |
| `title` | string | 问卷标题 |
| `description` | string | 问卷说明，可为空 |
| `status` | string | 当前固定为 `draft` |
| `createdAt` | datetime | 创建时间，UTC |
| `updatedAt` | datetime | 最后更新时间，UTC |

### 3.3 `responses`

本阶段只读取数量：

| 字段 | 类型 | 说明 |
|---|---|---|
| `surveyId` | ObjectId | 所属问卷 |
| `submittedAt` | datetime | 提交时间 |

答卷模块完成后，会在此基础上增加答案数组。统计接口不依赖答案的具体结构，因此可以保持调用方式不变。

## 4. 数据库接口

数据库查询集中在 repository 文件：

| 文件 | 公开函数 | 说明 |
|---|---|---|
| `common/db.py` | `init_db`、`get_db`、`ensure_indexes` | 建立连接和索引 |
| `auth/repository.py` | `create_user`、`find_by_username`、`find_by_id` | 用户读写 |
| `surveys/repository.py` | `create_survey`、`list_by_owner`、`find_by_id` | 问卷读写 |
| `analytics/repository.py` | `get_survey_stats` | 读取问卷统计 |

业务服务层只调用这些函数，不直接拼 MongoDB 查询。后续增加字段、索引或缓存时，优先修改 repository，而不是修改路由。

## 5. 权限与数据完整性

- 用户名在数据库层建立唯一索引。
- 密码使用 Werkzeug 的密码哈希函数保存。
- 创建问卷时，`ownerId` 只从登录会话中的当前用户获取，不接收前端提交的所有者字段。
- 问卷列表查询条件固定为 `ownerId = 当前用户 ID`。
- 查看统计前再次校验问卷所有者；不是所有者时统一返回“问卷不存在”，避免泄露问卷是否存在。
- 所有 POST 表单带 CSRF 校验。
- 登录成功后清空旧会话，再写入新的 `user_id`。

## 6. 测试覆盖

`tests/test_first_feature.py` 使用内存数据库替身，不依赖本机 MongoDB：

- 注册、登录、创建问卷、进入统计页。
- 问卷 `ownerId` 来自当前登录用户。
- 两个用户之间的问卷列表隔离。
- 其他用户直接访问统计 URL 返回 404。
- 重复用户名返回 409。
- 错误密码返回 401。
- 数据库中保存的是密码哈希，并存在注册时间。

## 7. 下一步扩展

1. 在 `surveys` 文档中加入题目数组，由题目模块负责校验。
2. 增加发布流程和分享码，状态从 `draft` 进入 `published`。
3. 建立 `responses` 的完整答卷结构。
4. 在 `analytics/repository.py` 中增加按题目聚合的函数，保持统计页路由不变。
