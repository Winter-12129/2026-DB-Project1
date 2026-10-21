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
    "survey_system_api_test",
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


def get(path):
    response = session.get(url(path), timeout=15)
    response.encoding = "utf-8"
    return response


def csrf_from(html):
    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        html,
    )
    check(match is not None, "页面中存在 CSRF token")
    return match.group(1)


def post_form(path, data, csrf_token):
    response = session.post(
        url(path),
        data={**data, "csrf_token": csrf_token},
        timeout=15,
    )
    response.encoding = "utf-8"
    return response


def post_json(path, payload, csrf_token):
    response = session.post(
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

    stats_page = get(f"/surveys/{survey_id}/stats")
    check("已提交答卷 2 份" in stats_page.text, "整卷统计可见")
    check("单选题" in stats_page.text, "统计页包含单选题")
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
