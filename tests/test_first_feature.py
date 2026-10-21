import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from analytics.service import get_survey_stats
from app import create_app
from config import Config


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    CSRF_ENABLED = False
    MONGO_ENSURE_INDEXES = False
    SESSION_COOKIE_SECURE = False


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, key, direction=-1):
        if isinstance(key, list):
            key = key[0][0]
        self.documents.sort(
            key=lambda document: document.get(key),
            reverse=(direction == -1),
        )
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self, unique_fields=None, unique_composite=None):
        self.documents = []
        self.unique_fields = unique_fields or []
        self.unique_composite = unique_composite or []

    def create_index(self, *args, **kwargs):
        return kwargs.get("name", "index")

    def insert_one(self, document):
        stored = dict(document)
        stored.setdefault("_id", ObjectId())
        for field in self.unique_fields:
            if any(
                existing.get(field) == stored.get(field)
                for existing in self.documents
            ):
                raise DuplicateKeyError(f"duplicate {field}")
        for fields in self.unique_composite:
            if all(stored.get(field) is not None for field in fields):
                duplicate = any(
                    all(
                        existing.get(field) == stored.get(field)
                        for field in fields
                    )
                    for existing in self.documents
                )
                if duplicate:
                    raise DuplicateKeyError(
                        f"duplicate {','.join(fields)}"
                    )
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    def find_one(self, filter_document):
        for document in self.documents:
            if all(
                document.get(key) == value
                for key, value in filter_document.items()
            ):
                return document
        return None

    def find(self, filter_document):
        return FakeCursor(
            [
                document
                for document in self.documents
                if all(
                    document.get(key) == value
                    for key, value in filter_document.items()
                )
            ]
        )

    def update_one(self, filter_document, update_document):
        document = self.find_one(filter_document)
        if document is None:
            return SimpleNamespace(modified_count=0)
        document.update(update_document.get("$set", {}))
        return SimpleNamespace(modified_count=1)

    def count_documents(self, filter_document):
        return len(
            [
                document
                for document in self.documents
                if all(
                    document.get(key) == value
                    for key, value in filter_document.items()
                )
            ]
        )


class FakeDB:
    def __init__(self):
        self.users = FakeCollection(unique_fields=["username"])
        self.surveys = FakeCollection(unique_fields=["shareCode"])
        self.responses = FakeCollection(
            unique_composite=[
                ("surveyId", "submissionToken"),
                ("surveyId", "participantKey"),
            ]
        )


class FirstFeatureTest(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.app = create_app(TestConfig, database=self.db)
        self.client = self.app.test_client()

    def register(self, client, username, password="password123"):
        return client.post(
            "/register",
            data={
                "username": username,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=True,
        )

    def login(self, client, username, password="password123"):
        return client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def create_survey(
        self,
        client,
        title,
        allow_anonymous=False,
        allow_multiple=False,
    ):
        return client.post(
            "/surveys/new",
            data={
                "title": title,
                "description": "问卷说明",
                "allow_anonymous": "1" if allow_anonymous else "",
                "allow_multiple": "1" if allow_multiple else "",
            },
            follow_redirects=True,
        )

    def add_question(self, client, survey_id, **fields):
        return client.post(
            f"/surveys/{survey_id}/questions",
            data=fields,
            follow_redirects=True,
        )

    def submit_response(self, share_code, answers, token):
        return self.client.post(
            f"/api/v1/surveys/{share_code}/responses",
            json={
                "answers": answers,
                "submissionToken": token,
            },
        )

    def test_register_login_create_and_stats(self):
        response = self.register(self.client, "alice")
        self.assertEqual(response.status_code, 200)
        self.assertIn("注册成功", response.get_data(as_text=True))

        response = self.login(self.client, "alice")
        self.assertEqual(response.status_code, 200)
        self.assertIn("我的问卷", response.get_data(as_text=True))

        response = self.client.post(
            "/surveys/new",
            data={
                "title": "Alice 问卷",
                "description": "第一份问卷",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alice 问卷", response.get_data(as_text=True))

        self.assertEqual(len(self.db.surveys.documents), 1)
        survey = self.db.surveys.documents[0]
        user = self.db.users.documents[0]
        self.assertEqual(survey["ownerId"], user["_id"])
        self.assertEqual(survey["status"], "draft")

        response = self.client.get(f"/surveys/{survey['_id']}/stats")
        self.assertEqual(response.status_code, 200)
        self.assertIn("已提交答卷", response.get_data(as_text=True))

    def test_create_survey_redirects_to_question_editor(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        response = self.client.post(
            "/surveys/new",
            data={
                "title": "进入出题页",
                "description": "创建后直接进入编辑",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        survey = self.db.surveys.documents[0]
        self.assertTrue(
            response.headers["Location"].endswith(
                f"/surveys/{survey['_id']}"
            )
        )

    def test_users_only_see_their_own_surveys(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.client.post(
            "/surveys/new",
            data={"title": "Alice 私有问卷"},
            follow_redirects=True,
        )
        survey = self.db.surveys.documents[0]

        self.client.post("/logout", follow_redirects=True)
        self.register(self.client, "bob")
        self.login(self.client, "bob")

        response = self.client.get("/surveys")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "Alice 私有问卷",
            response.get_data(as_text=True),
        )

        response = self.client.get(f"/surveys/{survey['_id']}/stats")
        self.assertEqual(response.status_code, 404)

    def test_duplicate_username_is_rejected(self):
        self.register(self.client, "alice")
        response = self.register(self.client, "alice")
        self.assertEqual(response.status_code, 409)
        self.assertIn("用户名已被使用", response.get_data(as_text=True))

    def test_wrong_password_is_rejected(self):
        self.register(self.client, "alice")
        response = self.login(self.client, "alice", password="wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertIn("用户名或密码错误", response.get_data(as_text=True))

    def test_password_is_hashed_and_created_at_exists(self):
        self.register(self.client, "alice")
        user = self.db.users.documents[0]
        self.assertNotEqual(user["passwordHash"], "password123")
        self.assertNotIn("password123", user["passwordHash"])
        self.assertIn("createdAt", user)

    def test_survey_creation_stores_share_code_and_anonymous_flag(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "匿名问卷", allow_anonymous=True)

        survey = self.db.surveys.documents[0]
        user = self.db.users.documents[0]
        self.assertEqual(survey["ownerId"], user["_id"])
        self.assertEqual(survey["status"], "draft")
        self.assertTrue(survey["allowAnonymous"])
        self.assertEqual(len(survey["shareCode"]), 10)

        response = self.client.get(f"/surveys/{survey['_id']}")
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("分享链接", text)
        self.assertIn(survey["shareCode"], text)

    def test_public_link_requires_login_when_anonymous_is_disabled(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "需要登录的问卷", allow_anonymous=False)
        survey = self.db.surveys.documents[0]
        share_code = survey["shareCode"]
        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="请选择",
            options="选项 A\n选项 B",
            required="1",
        )
        self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )

        self.client.post("/logout", follow_redirects=True)
        response = self.client.get(f"/survey/{share_code}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=", response.headers["Location"])

        self.register(self.client, "bob")
        response = self.client.post(
            "/login",
            data={
                "username": "bob",
                "password": "password123",
                "next": f"/survey/{share_code}",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("需要登录的问卷", response.get_data(as_text=True))

    def test_anonymous_public_link_opens_without_login(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "公开匿名问卷", allow_anonymous=True)
        survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="请选择",
            options="选项 A\n选项 B",
            required="1",
        )
        self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        self.client.post("/logout", follow_redirects=True)

        response = self.client.get(f"/survey/{survey['shareCode']}")
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("公开匿名问卷", text)
        self.assertIn("允许匿名填写", text)

    def test_publish_set_deadline_and_close(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "生命周期问卷")
        survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="请选择",
            options="选项 A\n选项 B",
            required="1",
        )

        response = self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("问卷已发布", response.get_data(as_text=True))
        self.assertEqual(survey["status"], "published")

        future = (
            datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)
        ).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            f"/surveys/{survey['_id']}/deadline",
            data={"deadline": future},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("截止时间已更新", response.get_data(as_text=True))
        self.assertIsNotNone(survey["deadline"])

        response = self.client.post(
            f"/surveys/{survey['_id']}/close",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("问卷已关闭", response.get_data(as_text=True))
        self.assertEqual(survey["status"], "closed")

        self.client.post("/logout", follow_redirects=True)
        response = self.client.get(f"/survey/{survey['shareCode']}")
        self.assertIn("问卷已关闭", response.get_data(as_text=True))

    def test_other_user_cannot_manage_survey(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "Alice 的管理问卷")
        survey = self.db.surveys.documents[0]

        self.client.post("/logout", follow_redirects=True)
        self.register(self.client, "bob")
        self.login(self.client, "bob")

        response = self.client.get(f"/surveys/{survey['_id']}")
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(survey["status"], "draft")

    def test_publish_requires_question(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "空问卷")
        survey = self.db.surveys.documents[0]

        response = self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "发布前至少需要一道题",
            response.get_data(as_text=True),
        )
        self.assertEqual(survey["status"], "draft")

    def test_single_choice_branching_and_server_replay(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "分支问卷", allow_multiple=True)
        survey = self.db.surveys.documents[0]

        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="选择分支",
            options="A\nB",
            required="1",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="被跳过的必填题",
            required="1",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="B 分支",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="中间题",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="A 分支",
        )

        questions = survey["questions"]
        q1, q2, q3, q4, q5 = questions
        q1_a = q1["options"][0]["id"]
        q1_b = q1["options"][1]["id"]

        self.client.post(
            f"/surveys/{survey['_id']}/questions/{q1['id']}/rules",
            data={
                "target_question_id": q5["id"],
                "option_id": q1_a,
                "priority": "1",
            },
            follow_redirects=True,
        )
        self.client.post(
            f"/surveys/{survey['_id']}/questions/{q1['id']}/rules",
            data={
                "target_question_id": q3["id"],
                "option_id": q1_b,
                "priority": "2",
            },
            follow_redirects=True,
        )
        self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        self.assertEqual(survey["status"], "published")

        response = self.submit_response(
            survey["shareCode"],
            {
                q1["id"]: q1_a,
                q2["id"]: "这条答案属于被跳过的题",
            },
            "single-token-1",
        )
        self.assertEqual(response.status_code, 201)
        first_response = self.db.responses.documents[0]
        self.assertEqual(
            first_response["visitedQuestionIds"],
            [q1["id"], q5["id"]],
        )
        self.assertEqual(
            [answer["questionId"] for answer in first_response["answers"]],
            [q1["id"]],
        )

        response = self.submit_response(
            survey["shareCode"],
            {q1["id"]: q1_b},
            "single-token-2",
        )
        self.assertEqual(response.status_code, 201)
        second_response = self.db.responses.documents[1]
        self.assertEqual(
            second_response["visitedQuestionIds"],
            [q1["id"], q3["id"], q4["id"], q5["id"]],
        )

    def test_multiple_and_number_branching_validation(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "多选和数字分支", allow_multiple=True)
        survey = self.db.surveys.documents[0]

        self.add_question(
            self.client,
            survey["_id"],
            type="multiple_choice",
            title="多选题",
            options="A\nB\nC",
            min_selections="1",
            max_selections="2",
            required="1",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="number",
            title="数字题",
            min_number="0",
            max_number="100",
            integer_only="1",
            required="1",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="普通题",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="多选目标",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="数字目标",
        )

        q1, q2, q3, q4, q5 = survey["questions"]
        a_id, b_id, c_id = [
            option["id"] for option in q1["options"]
        ]

        self.client.post(
            f"/surveys/{survey['_id']}/questions/{q1['id']}/rules",
            data={
                "target_question_id": q4["id"],
                "option_ids": [a_id, c_id],
                "match": "any",
                "priority": "1",
            },
            follow_redirects=True,
        )
        self.client.post(
            f"/surveys/{survey['_id']}/questions/{q2['id']}/rules",
            data={
                "target_question_id": q5["id"],
                "operator": "between",
                "min_value": "18",
                "max_value": "60",
                "priority": "1",
            },
            follow_redirects=True,
        )
        self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )

        response = self.submit_response(
            survey["shareCode"],
            {q1["id"]: [a_id]},
            "multi-token-1",
        )
        self.assertEqual(response.status_code, 201)
        first_response = self.db.responses.documents[0]
        self.assertEqual(
            first_response["visitedQuestionIds"],
            [q1["id"], q4["id"], q5["id"]],
        )

        response = self.submit_response(
            survey["shareCode"],
            {
                q1["id"]: [b_id],
                q2["id"]: 20,
            },
            "multi-token-2",
        )
        self.assertEqual(response.status_code, 201)
        second_response = self.db.responses.documents[1]
        self.assertEqual(
            second_response["visitedQuestionIds"],
            [q1["id"], q2["id"], q5["id"]],
        )

        response = self.submit_response(
            survey["shareCode"],
            {
                q1["id"]: [a_id, b_id, c_id],
                q2["id"]: 20,
            },
            "multi-token-3",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self.db.responses.documents), 2)

    def test_submission_idempotency_and_multiple_response_policy(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "单次提交问卷")
        first_survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            first_survey["_id"],
            type="single_choice",
            title="请选择",
            options="A\nB",
            required="1",
        )
        self.client.post(
            f"/surveys/{first_survey['_id']}/publish",
            follow_redirects=True,
        )
        first_option = first_survey["questions"][0]["options"][0]["id"]

        response = self.submit_response(
            first_survey["shareCode"],
            {first_survey["questions"][0]["id"]: first_option},
            "same-token",
        )
        self.assertEqual(response.status_code, 201)
        response = self.submit_response(
            first_survey["shareCode"],
            {first_survey["questions"][0]["id"]: first_option},
            "same-token",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["idempotent"])
        self.assertEqual(len(self.db.responses.documents), 1)

        response = self.submit_response(
            first_survey["shareCode"],
            {first_survey["questions"][0]["id"]: first_option},
            "different-token",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.db.responses.documents), 1)

        self.create_survey(
            self.client,
            "多次提交问卷",
            allow_multiple=True,
        )
        second_survey = self.db.surveys.documents[1]
        self.add_question(
            self.client,
            second_survey["_id"],
            type="single_choice",
            title="请选择",
            options="A\nB",
            required="1",
        )
        self.client.post(
            f"/surveys/{second_survey['_id']}/publish",
            follow_redirects=True,
        )
        second_option = second_survey["questions"][0]["options"][0]["id"]
        for token in ("multi-1", "multi-2"):
            response = self.submit_response(
                second_survey["shareCode"],
                {second_survey["questions"][0]["id"]: second_option},
                token,
            )
            self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.db.responses.documents), 3)

    def test_statistics_for_all_question_types(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "统计问卷", allow_multiple=True)
        survey = self.db.surveys.documents[0]

        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="单选题",
            options="是\n否",
            required="1",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="multiple_choice",
            title="多选题",
            options="A\nB\nC",
            min_selections="0",
            max_selections="3",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="文本题",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="number",
            title="数字题",
            min_number="0",
            max_number="100",
        )

        q1, q2, q3, q4 = survey["questions"]
        yes, no = [option["id"] for option in q1["options"]]
        a, b, c = [option["id"] for option in q2["options"]]
        user = self.db.users.documents[0]
        visited = [q1["id"], q2["id"], q3["id"], q4["id"]]
        submitted = datetime.now(timezone.utc)
        self.db.responses.documents.extend(
            [
                {
                    "surveyId": survey["_id"],
                    "surveyVersion": 1,
                    "answers": [
                        {"questionId": q1["id"], "type": "single_choice", "value": yes},
                        {"questionId": q2["id"], "type": "multiple_choice", "value": [a, b]},
                        {"questionId": q3["id"], "type": "text", "value": "很好"},
                        {"questionId": q4["id"], "type": "number", "value": 10},
                    ],
                    "visitedQuestionIds": visited,
                    "submittedAt": submitted,
                },
                {
                    "surveyId": survey["_id"],
                    "surveyVersion": 1,
                    "answers": [
                        {"questionId": q1["id"], "type": "single_choice", "value": yes},
                        {"questionId": q2["id"], "type": "multiple_choice", "value": [b]},
                        {"questionId": q3["id"], "type": "text", "value": "20"},
                        {"questionId": q4["id"], "type": "number", "value": 20},
                    ],
                    "visitedQuestionIds": visited,
                    "submittedAt": submitted + timedelta(seconds=1),
                },
            ]
        )

        with self.app.app_context():
            stats = get_survey_stats(
                str(survey["_id"]),
                user["_id"],
            )

        self.assertEqual(stats["totalResponses"], 2)
        by_question = {
            question["questionId"]: question
            for question in stats["questions"]
        }
        single = by_question[q1["id"]]
        self.assertEqual(single["answeredCount"], 2)
        single_counts = {
            option["label"]: option["count"]
            for option in single["options"]
        }
        self.assertEqual(single_counts, {"是": 2, "否": 0})

        multiple = by_question[q2["id"]]
        multiple_counts = {
            option["label"]: option["count"]
            for option in multiple["options"]
        }
        self.assertEqual(multiple_counts, {"A": 1, "B": 2, "C": 0})

        text = by_question[q3["id"]]
        self.assertEqual(text["textAnswers"], ["很好", "20"])
        self.assertEqual(text["numeric"]["count"], 1)
        self.assertEqual(text["numeric"]["average"], 20.0)

        number = by_question[q4["id"]]
        self.assertEqual(number["numeric"]["count"], 2)
        self.assertEqual(number["numeric"]["average"], 15.0)
        self.assertEqual(number["numeric"]["min"], 10.0)
        self.assertEqual(number["numeric"]["max"], 20.0)

        with self.app.app_context():
            filtered = get_survey_stats(
                str(survey["_id"]),
                user["_id"],
                question_id=q1["id"],
            )
        self.assertEqual(len(filtered["questions"]), 1)
        self.assertEqual(
            filtered["questions"][0]["questionId"],
            q1["id"],
        )


if __name__ == "__main__":
    unittest.main()
