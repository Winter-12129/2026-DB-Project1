# 最终提交清单

## 1. 代码

必须提交：

- 后端入口与业务代码：`app.py`、`config.py`
- 业务模块：`auth/`、`surveys/`、`questions/`、`question_bank/`、`logic/`、`publishing/`、`responses/`、`analytics/`
- 公共基础设施：`common/`
- 页面和样式：`templates/`、`static/`
- 依赖文件：`requirements.txt`、`requirements-dev.txt`

MongoDB Schema：

- 数据库级 `$jsonSchema`：`common/schema.py`
- 连接、Validator 和索引：`common/db.py`
- 字段和嵌套说明：`docs/08-MongoDB-Schema.md`

配置说明：

- 环境变量和启动步骤：`docs/09-配置说明.md`

运行方式：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:SECRET_KEY = "请替换为随机字符串"
$env:MONGO_URI = "mongodb://127.0.0.1:27017"
$env:MONGO_DB_NAME = "survey_system"

.\.venv\Scripts\python.exe app.py
```

## 2. 文档

- 系统说明、前后端版本、表格嵌套和 API：`docs/07-系统设计与提交说明.md`
- 数据库设计：`docs/08-MongoDB-Schema.md`
- 题目库、共享、版本和跨问卷统计：`docs/13-question-bank.md`
- 查询与索引证据：`docs/12-查询与索引证据.md`

## 3. 测试用例

- 测试步骤、输入、预期输出、实际输出和结果：`docs/06-测试案例与结果.md`
- 自动测试代码：`tests/`

执行：

```powershell
python -m unittest discover -s tests -v
```

当前结果：24 个单元测试全部通过。

## 4. 项目完成报告

- 精简的第二阶段报告：`docs/10-项目完成报告.md`
- AI 提示词、生成结果和修改记录：`docs/11-AI使用日志.md`

报告只描述第二阶段新增的题目库、共享、版本、题目 ID 查询和跨问卷统计，不重复第一阶段功能。

## 建议提交目录

```text
项目根目录/
├─ app.py
├─ config.py
├─ requirements.txt
├─ requirements-dev.txt
├─ auth/
├─ surveys/
├─ questions/
├─ question_bank/
├─ logic/
├─ publishing/
├─ responses/
├─ analytics/
├─ common/
├─ templates/
├─ static/
├─ tests/
├─ docs/
├─ README.md
└─ SUBMISSION.md
```