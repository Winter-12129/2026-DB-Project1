"""对运行中的 Flask Web 服务做真实 HTTP 测试。

主流程：
注册 -> 登录 -> 创建问卷 -> 添加四类题目 -> 配置跳转 -> 发布
-> 打开公开链接 -> 调用提交 API -> 查看整卷/单题统计。

该脚本使用独立测试数据库，不会删除日常使用的 survey_system 数据库。
"""

import os
import re
import sys
import time

import requests
from bson import ObjectId
from pymongo import MongoClient


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


BASE_URL = os.environ.get(
    "SURVEY_TEST_BASE_URL",
    "http://127.0.0.1:5001",
).rstrip("/")
MONGO_URI = os.environ.get(
    "SURVEY_TEST_MONGO_URI",
    "mongodb://127.0.0.1:27018",
)
DB_NAME = os.environ.get(
    "SURVEY_TEST_DB_NAME",
    "survey_system_version_test",
)

session = requests.Session()
mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = mongo[DB_NAME]


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def url(path):
    return f"{BASE_URL}{path}"


def get(path, client=None):
    client = client or session
    response = client.get(url(path), timeout=15)
    response.encoding = "utf-8"
    return response


def csrf_from(html):
    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        html,
    )
    check(match is not None, "页面中存在 CSRF token")
    return match.group(1)


def post_form(path, data, csrf_token, client=None):
    client = client or session
    response = client.post(
        url(path),
        data={**data, "csrf_token": csrf_token},
        timeout=15,
    )
    response.encoding = "utf-8"
    return response


def post_json(path, payload, csrf_token, client=None):
    client = client or session
    response = client.post(
        url(path),
        json=payload,
        headers={"X-CSRF-Token": csrf_token},
        timeout=15,
    )
    response.encoding = "utf-8"
    return response


def wait_for_server():
    for _ in range(40):
        try:
            response = session.get(url("/login"), timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Flask 服务未在 {BASE_URL} 启动")


def main():
    wait_for_server()

    # 第二个用户用于验证题目共享。
    bob_session = requests.Session()
    bob_register_page = bob_session.get(url("/register"), timeout=15)
    bob_register_page.encoding = "utf-8"
    bob_csrf = csrf_from(bob_register_page.text)
    bob_register = bob_session.post(
        url("/register"),
        data={
            "username": "http_bob",
            "password": "password123",
            "confirm_password": "password123",
            "csrf_token": bob_csrf,
        },
        timeout=15,
    )
    bob_register.encoding = "utf-8"
    check("注册成功" in bob_register.text, "共享目标用户注册成功")

    # 注册和登录
    register_page = get("/register")
    csrf = csrf_from(register_page.text)
    response = post_form(
        "/register",
        {
            "username": "http_tester",
            "password": "password123",
            "confirm_password": "password123",
        },
        csrf,
    )
    check("注册成功" in response.text, "注册接口可访问")

    login_page = get("/login")
    csrf = csrf_from(login_page.text)
    response = session.post(
        url("/login"),
        data={
            "username": "http_tester",
            "password": "password123",
            "csrf_token": csrf,
        },
        timeout=15,
    )
    response.encoding = "utf-8"
    check("我的问卷" in response.text, "登录成功并进入问卷列表")

    direct_bank_page = get("/question-bank/new")
    direct_bank_csrf = csrf_from(direct_bank_page.text)
    direct_bank = post_form(
        "/question-bank/new",
        {
            "type": "text",
            "title": "HTTP 常用题目",
            "aliases": "HTTP 固定问题",
        },
        direct_bank_csrf,
    )
    check("常用题目已保存" in direct_bank.text, "题目库支持直接新建常用题")

    # 创建后必须进入出题页
    create_page = get("/surveys/new")
    csrf = csrf_from(create_page.text)
    response = post_form(
        "/surveys/new",
        {
            "title": "HTTP 自动化测试问卷",
            "description": "覆盖四类题型、跳转和统计",
            "allow_anonymous": "",
            "allow_multiple": "1",
        },
        csrf,
    )
    check(
        "/surveys/" in response.url
        and "题目与跳转" in response.text,
        "创建后直接进入题目与跳转页",
    )
    survey_id = response.url.rstrip("/").split("/")[-1]
    survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    check(survey is not None, "MongoDB 中已生成问卷文档")

    # 添加四种题目
    detail = get(f"/surveys/{survey_id}")
    csrf = csrf_from(detail.text)
    question_specs = [
        {
            "type": "single_choice",
            "title": "单选题",
            "options": "A\nB",
            "required": "1",
            "save_to_bank": "1",
            "bank_aliases": "首题别名",
        },
        {
            "type": "multiple_choice",
            "title": "多选题",
            "options": "A\nB\nC",
            "min_selections": "1",
            "max_selections": "2",
            "required": "1",
        },
        {
            "type": "text",
            "title": "文本题",
            "min_length": "0",
            "max_length": "100",
        },
        {
            "type": "number",
            "title": "数字题",
            "min_number": "0",
            "max_number": "100",
            "integer_only": "1",
            "required": "1",
        },
    ]
    for spec in question_specs:
        response = post_form(
            f"/surveys/{survey_id}/questions",
            spec,
            csrf,
        )
        check("题目已添加" in response.text, f"添加题目：{spec['title']}")

    survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    q1, q2, q3, q4 = survey["questions"]
    q1_a, q1_b = [option["id"] for option in q1["options"]]
    q2_a, q2_b, _ = [option["id"] for option in q2["options"]]

    bank_family = db.question_bank.find_one({"title": "单选题"})
    check(bank_family is not None, "题目保存进入题目库")
    bank_page = get("/question-bank")
    check(
        "单选题" in bank_page.text and "1 个版本" in bank_page.text,
        "题目库页面可查看题目",
    )

    family_id = str(bank_family["_id"])
    base_version_id = bank_family["currentVersionId"]
    version_form = get(
        f"/question-bank/{family_id}/versions/new?base={base_version_id}"
    )
    version_csrf = csrf_from(version_form.text)
    version_response = post_form(
        f"/question-bank/{family_id}/versions/new",
        {
            "base_version_id": base_version_id,
            "type": "single_choice",
            "title": "单选题新版",
            "options": "A\nB",
        },
        version_csrf,
    )
    check("新版本已保存" in version_response.text, "创建题库新版本")
    bank_family = db.question_bank.find_one(
        {"_id": ObjectId(family_id)}
    )
    check(len(bank_family["versions"]) == 2, "新旧版本并存")
    check(
        bank_family["versions"][1]["parentVersionId"] == base_version_id,
        "新版本记录父版本"
    )

    new_version_id = bank_family["versions"][1]["id"]
    replace_response = post_form(
        f"/question-bank/{family_id}/versions/new",
        {
            "base_version_id": new_version_id,
            "save_mode": "replace",
            "type": "single_choice",
            "title": "单选题直接修改",
            "options": "A\nB",
        },
        version_csrf,
    )
    check(
        "当前版本内容已更新" in replace_response.text,
        "可以选择直接修改当前版本",
    )
    bank_family = db.question_bank.find_one(
        {"_id": ObjectId(family_id)}
    )
    check(len(bank_family["versions"]) == 2, "直接修改不会新增版本")
    check(
        bank_family["versions"][1]["title"] == "单选题直接修改",
        "直接修改更新所选版本内容",
    )

    version_csrf = csrf_from(get("/question-bank").text)
    restore_response = post_form(
        f"/question-bank/{family_id}/versions/{base_version_id}/restore",
        {},
        version_csrf,
    )
    check("已切换当前版本" in restore_response.text, "恢复旧版本")
    bank_family = db.question_bank.find_one(
        {"_id": ObjectId(family_id)}
    )
    check(bank_family["currentVersionId"] == base_version_id, "恢复后当前指针正确")

    response = post_form(
        f"/question-bank/{family_id}/share",
        {"username": "http_bob"},
        csrf,
    )
    check("已共享给 http_bob" in response.text, "题目共享给第二个用户")

    bob_login_page = bob_session.get(url("/login"), timeout=15)
    bob_login_page.encoding = "utf-8"
    bob_login_csrf = csrf_from(bob_login_page.text)
    bob_login = bob_session.post(
        url("/login"),
        data={
            "username": "http_bob",
            "password": "password123",
            "csrf_token": bob_login_csrf,
        },
        timeout=15,
    )
    bob_login.encoding = "utf-8"
    check("我的问卷" in bob_login.text, "共享目标用户登录")
    bob_bank = get("/question-bank", client=bob_session)
    check("共享给我的题目" in bob_bank.text, "被共享用户看到题库题目")

    bob_create_page = get("/surveys/new", client=bob_session)
    bob_create_csrf = csrf_from(bob_create_page.text)
    bob_create = post_form(
        "/surveys/new",
        {"title": "Bob 共享题目问卷", "description": "使用共享题目"},
        bob_create_csrf,
        client=bob_session,
    )
    bob_survey_id = bob_create.url.rstrip("/").split("/")[-1]
    bob_detail = get(f"/surveys/{bob_survey_id}", client=bob_session)
    bob_detail_csrf = csrf_from(bob_detail.text)
    bob_add = post_form(
        f"/surveys/{bob_survey_id}/questions/from-bank",
        {
            "bank_version_id": bank_family["versions"][0]["id"],
            "required": "1",
        },
        bob_detail_csrf,
        client=bob_session,
    )
    check("已从题目库添加题目" in bob_add.text, "被共享用户使用题目")
    bob_survey = db.surveys.find_one({"_id": ObjectId(bob_survey_id)})
    check(
        bob_survey["questions"][0]["sourceVersionId"]
        == bank_family["versions"][0]["id"],
        "共享题目按快照加入用户问卷",
    )

    # 新建第二份问卷，并从题目库添加同一道题。
    response = post_form(
        "/surveys/new",
        {
            "title": "题库使用问卷",
            "description": "从题目库添加题目",
        },
        csrf,
    )
    second_survey_id = response.url.rstrip("/").split("/")[-1]
    version_id = bank_family["versions"][0]["id"]
    response = post_form(
        f"/surveys/{second_survey_id}/questions/from-bank",
        {
            "bank_version_id": version_id,
            "required": "1",
        },
        csrf,
    )
    check("已从题目库添加题目" in response.text, "从题目库添加题目")
    second_survey = db.surveys.find_one({"_id": ObjectId(second_survey_id)})
    check(
        second_survey["questions"][0]["sourceVersionId"] == version_id,
        "第二份问卷保存题库快照",
    )
    second_question_id = second_survey["questions"][0]["id"]
    post_form(
        f"/surveys/{second_survey_id}/publish",
        {},
        csrf,
    )
    second_survey = db.surveys.find_one({"_id": ObjectId(second_survey_id)})
    check(second_survey["status"] == "published", "第二份问卷发布")

    # 单选题选 A 时跳到数字题
    response = post_form(
        f"/surveys/{survey_id}/questions/{q1['id']}/rules",
        {
            "target_question_id": q4["id"],
            "option_id": q1_a,
            "priority": "1",
        },
        csrf,
    )
    check("跳转规则已添加" in response.text, "保存单选题跳转规则")

    response = post_form(
        f"/surveys/{survey_id}/publish",
        {},
        csrf,
    )
    check("问卷已发布" in response.text, "发布问卷")

    share_code = survey["shareCode"]
    public_page = get(f"/survey/{share_code}")
    check(
        "HTTP 自动化测试问卷" in public_page.text
        and "fill-app" in public_page.text,
        "公开链接可进入填写页面",
    )

    # 两个答卷：第一个走跳转路径，第二个走完整路径
    first = post_json(
        f"/api/v1/surveys/{share_code}/responses",
        {
            "answers": {
                q1["id"]: q1_a,
                q4["id"]: 10,
            },
            "submissionToken": "http-token-1",
        },
        csrf,
    )
    check(first.status_code == 201, "第一次 API 提交成功")

    second = post_json(
        f"/api/v1/surveys/{share_code}/responses",
        {
            "answers": {
                q1["id"]: q1_b,
                q2["id"]: [q2_a, q2_b],
                q3["id"]: "20",
                q4["id"]: 20,
            },
            "submissionToken": "http-token-2",
        },
        csrf,
    )
    check(second.status_code == 201, "第二次 API 提交成功")

    duplicate = post_json(
        f"/api/v1/surveys/{share_code}/responses",
        {
            "answers": {
                q1["id"]: q1_a,
                q4["id"]: 10,
            },
            "submissionToken": "http-token-1",
        },
        csrf,
    )
    check(
        duplicate.status_code == 200
        and duplicate.json().get("idempotent") is True,
        "重复提交 token 幂等返回",
    )

    responses = list(
        db.responses.find({"surveyId": ObjectId(survey_id)})
    )
    check(len(responses) == 2, "两条不同提交均已保存")
    by_token = {
        response["submissionToken"]: response
        for response in responses
    }
    check(
        by_token["http-token-1"]["visitedQuestionIds"]
        == [q1["id"], q4["id"]],
        "第一条答卷按规则跳过了中间题",
    )
    check(
        by_token["http-token-2"]["visitedQuestionIds"]
        == [q1["id"], q2["id"], q3["id"], q4["id"]],
        "第二条答卷按默认顺序访问全部题",
    )

    cross_response = post_json(
        f"/api/v1/surveys/{second_survey['shareCode']}/responses",
        {
            "answers": {second_question_id: q1_a},
            "submissionToken": "http-cross-token",
        },
        csrf,
    )
    check(cross_response.status_code == 201, "第二份问卷提交跨卷统计答卷")

    cross_page = get(f"/question-bank/insights/{family_id}")
    check(
        survey_id in cross_page.text
        and second_survey_id in cross_page.text
        and "跨问卷" in cross_page.text,
        "题库页面返回使用问卷 ID 和跨问卷分析",
    )
    cross_api = get(f"/api/v1/question-bank/insights/{family_id}")
    cross_payload = cross_api.json()
    check(cross_payload["surveyCount"] == 2, "跨问卷统计聚合两份问卷")
    check(cross_payload["answeredCount"] == 3, "跨问卷统计合并三份答案")
    check(cross_payload["versionBreakdown"], "跨问卷统计包含版本分析")

    lookup_response = session.get(
        url(f"/question-bank/lookup?question_id={version_id}"),
        allow_redirects=False,
        timeout=15,
    )
    check(
        lookup_response.status_code == 302
        and f"/question-bank/insights/{version_id}" in lookup_response.headers.get("Location", ""),
        "题目 ID 查询系统可以解析版本 ID",
    )

    stats_page = get(f"/surveys/{survey_id}/stats")
    check("已提交答卷 2 份" in stats_page.text, "整卷统计可见")
    check("单选题" in stats_page.text, "统计页包含单选题")
    check("跨问卷分析" in stats_page.text, "单卷统计提供跨问卷入口")
    check("多选题" in stats_page.text, "统计页包含多选题")
    check("文本题" in stats_page.text, "统计页包含文本题")
    check("数字题" in stats_page.text, "统计页包含数字题")
    check("平均值" in stats_page.text, "数字题显示平均值")

    question_stats = get(
        f"/surveys/{survey_id}/stats?questionId={q1['id']}"
    )
    check(
        question_stats.status_code == 200
        and "第 1 题" in question_stats.text,
        "单题统计筛选可用",
    )

    print("\nHTTP 测试全部通过。")


if __name__ == "__main__":
    try:
        main()
    finally:
        mongo.drop_database(DB_NAME)
