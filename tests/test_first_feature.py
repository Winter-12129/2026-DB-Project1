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

    def _matches(self, document, key, value):
        actual = document.get(key)
        if isinstance(value, dict) and "$elemMatch" in value:
            if not isinstance(actual, list):
                return False
            condition = value["$elemMatch"]
            return any(
                isinstance(item, dict)
                and all(
                    self._matches(item, field, expected)
                    for field, expected in condition.items()
                )
                for item in actual
            )
        if isinstance(actual, list) and not isinstance(value, list):
            return value in actual
        return actual == value

    def find_one(self, filter_document):
        for document in self.documents:
            if all(
                self._matches(document, key, value)
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
                    self._matches(document, key, value)
                    for key, value in filter_document.items()
                )
            ]
        )

    def update_one(self, filter_document, update_document):
        document = self.find_one(filter_document)
        if document is None:
            return SimpleNamespace(modified_count=0)
        document.update(update_document.get("$set", {}))
        for key, value in update_document.get("$addToSet", {}).items():
            current = document.setdefault(key, [])
            if value not in current:
                current.append(value)
        for key, value in update_document.get("$pull", {}).items():
            current = document.get(key, [])
            if isinstance(current, list) and value in current:
                current.remove(value)
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

    def delete_one(self, filter_document):
        for index, document in enumerate(self.documents):
            if all(
                document.get(key) == value
                for key, value in filter_document.items()
            ):
                self.documents.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


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
        self.question_bank = FakeCollection()


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

    def test_question_bank_create_directly(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")

        page = self.client.get("/question-bank/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("新建常用题目", page.get_data(as_text=True))

        payload = {
            "type": "single_choice",
            "title": "常用联系方式",
            "options": "电话\n邮件",
            "aliases": "联系方式",
        }
        response = self.client.post(
            "/question-bank/new",
            data=payload,
            follow_redirects=True,
        )
        self.assertIn("常用题目已保存", response.get_data(as_text=True))
        self.assertEqual(len(self.db.question_bank.documents), 1)
        family = self.db.question_bank.documents[0]
        self.assertEqual(family["title"], "常用联系方式")
        self.assertEqual(len(family["versions"]), 1)

        response = self.client.post(
            "/question-bank/new",
            data=payload,
            follow_redirects=True,
        )
        self.assertIn("未重复创建", response.get_data(as_text=True))
        self.assertEqual(len(self.db.question_bank.documents), 1)
        self.assertEqual(len(family["versions"]), 1)

    def test_question_bank_dedupes_and_creates_versions(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "题库来源问卷")
        survey = self.db.surveys.documents[0]

        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="姓名",
            save_to_bank="1",
            bank_aliases="你的名字是",
        )
        self.add_question(
            self.client,
            survey["_id"],
            type="single_choice",
            title="姓名",
            options="A\nB",
            save_to_bank="1",
        )
        # 通过别名加入且内容一致，不应新增第三个版本。
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="你的名字是",
            save_to_bank="1",
        )

        self.assertEqual(len(self.db.question_bank.documents), 1)
        family = self.db.question_bank.documents[0]
        self.assertEqual(len(family["versions"]), 2)
        self.assertIn("你的名字是", family["aliases"])

        response = self.client.get("/question-bank")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("姓名", page)
        self.assertIn("2 个版本", page)

    def test_add_question_from_bank_to_another_survey(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "题库来源问卷")
        first = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            first["_id"],
            type="text",
            title="姓名",
            save_to_bank="1",
        )
        version_id = self.db.question_bank.documents[0]["versions"][0]["id"]

        self.create_survey(self.client, "使用题库的新问卷")
        second = self.db.surveys.documents[1]
        response = self.client.post(
            f"/surveys/{second['_id']}/questions/from-bank",
            data={
                "bank_version_id": version_id,
                "required": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(second["questions"]), 1)
        question = second["questions"][0]
        self.assertEqual(question["title"], "姓名")
        self.assertEqual(question["sourceVersionId"], version_id)
        self.assertTrue(question["required"])

        # 同一题库版本不能在同一问卷里重复添加。
        self.client.post(
            f"/surveys/{second['_id']}/questions/from-bank",
            data={"bank_version_id": version_id},
            follow_redirects=True,
        )
        self.assertEqual(len(second["questions"]), 1)


    def test_question_bank_sharing_between_users(self):
        self.register(self.client, "bob")
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "共享来源问卷")
        alice_survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            alice_survey["_id"],
            type="text",
            title="姓名",
            save_to_bank="1",
        )
        family = self.db.question_bank.documents[0]
        family_id = str(family["_id"])
        version_id = family["versions"][0]["id"]

        response = self.client.post(
            f"/question-bank/{family_id}/share",
            data={"username": "bob"},
            follow_redirects=True,
        )
        self.assertIn("已共享给 bob", response.get_data(as_text=True))
        bob = next(
            user for user in self.db.users.documents
            if user["username"] == "bob"
        )
        self.assertIn(bob["_id"], family["sharedWith"])

        self.client.post("/logout", follow_redirects=True)
        self.login(self.client, "bob")
        response = self.client.get("/question-bank")
        text = response.get_data(as_text=True)
        self.assertIn("共享给我的题目", text)
        self.assertIn("来自 alice", text)

        forbidden = self.client.get(
            f"/question-bank/{family_id}/versions/new"
        )
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(len(family["versions"]), 1)

        self.create_survey(self.client, "Bob 使用共享题目")
        bob_survey = next(
            survey for survey in self.db.surveys.documents
            if survey["title"] == "Bob 使用共享题目"
        )
        response = self.client.post(
            f"/surveys/{bob_survey['_id']}/questions/from-bank",
            data={"bank_version_id": version_id, "required": "1"},
            follow_redirects=True,
        )
        self.assertIn("已从题目库添加题目", response.get_data(as_text=True))
        self.assertEqual(
            bob_survey["questions"][0]["sourceVersionId"],
            version_id,
        )
    def test_question_bank_versions_and_restore(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "版本来源问卷")
        survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="姓名",
            save_to_bank="1",
        )
        family = self.db.question_bank.documents[0]
        family_id = str(family["_id"])
        base_id = family["currentVersionId"]
        self.assertIsNotNone(base_id)

        form_page = self.client.get(
            f"/question-bank/{family_id}/versions/new?base={base_id}"
        )
        self.assertEqual(form_page.status_code, 200)
        response = self.client.post(
            f"/question-bank/{family_id}/versions/new",
            data={
                "base_version_id": base_id,
                "type": "text",
                "title": "请填写姓名",
                "options": "",
            },
            follow_redirects=True,
        )
        self.assertIn("新版本已保存", response.get_data(as_text=True))
        self.assertEqual(len(family["versions"]), 2)
        new_version = family["versions"][1]
        self.assertEqual(new_version["parentVersionId"], base_id)
        self.assertEqual(family["currentVersionId"], new_version["id"])

        response = self.client.post(
            f"/question-bank/{family_id}/versions/{base_id}/restore",
            follow_redirects=True,
        )
        self.assertIn("已切换当前版本", response.get_data(as_text=True))
        self.assertEqual(family["currentVersionId"], base_id)
        self.assertEqual(len(family["versions"]), 2)

        self.create_survey(self.client, "使用旧版本问卷")
        target = next(
            item for item in self.db.surveys.documents
            if item["title"] == "使用旧版本问卷"
        )
        response = self.client.post(
            f"/surveys/{target['_id']}/questions/from-bank",
            data={"bank_version_id": base_id},
            follow_redirects=True,
        )
        self.assertIn("已从题目库添加题目", response.get_data(as_text=True))
        self.assertEqual(
            target["questions"][0]["sourceVersionId"],
            base_id,
        )

    def test_question_version_can_replace_or_create(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "版本保存方式问卷")
        survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="姓名",
            save_to_bank="1",
        )
        family = self.db.question_bank.documents[0]
        family_id = str(family["_id"])
        base_id = family["currentVersionId"]
        original_snapshot_title = survey["questions"][0]["title"]

        response = self.client.post(
            f"/question-bank/{family_id}/versions/new",
            data={
                "base_version_id": base_id,
                "save_mode": "replace",
                "type": "text",
                "title": "请填写姓名",
            },
            follow_redirects=True,
        )
        self.assertIn("当前版本内容已更新", response.get_data(as_text=True))
        self.assertEqual(len(family["versions"]), 1)
        self.assertEqual(family["versions"][0]["id"], base_id)
        self.assertEqual(family["versions"][0]["title"], "请填写姓名")
        self.assertEqual(survey["questions"][0]["title"], original_snapshot_title)

        response = self.client.post(
            f"/question-bank/{family_id}/versions/new",
            data={
                "base_version_id": base_id,
                "save_mode": "new",
                "type": "text",
                "title": "姓名（新版）",
            },
            follow_redirects=True,
        )
        self.assertIn("新版本已保存", response.get_data(as_text=True))
        self.assertEqual(len(family["versions"]), 2)
        self.assertEqual(family["versions"][1]["parentVersionId"], base_id)

    def test_cross_survey_question_usage_and_statistics(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "第一份年龄问卷")
        first = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            first["_id"],
            type="number",
            title="你的年龄",
            min_number="0",
            max_number="120",
            integer_only="1",
            save_to_bank="1",
        )
        family = self.db.question_bank.documents[0]
        family_id = str(family["_id"])
        version_id = family["currentVersionId"]

        self.create_survey(self.client, "第二份年龄问卷")
        second = self.db.surveys.documents[1]
        response = self.client.post(
            f"/surveys/{second['_id']}/questions/from-bank",
            data={"bank_version_id": version_id},
            follow_redirects=True,
        )
        self.assertIn("已从题目库添加题目", response.get_data(as_text=True))

        now = datetime.now(timezone.utc)
        response_rows = [
            (first, first["questions"][0]["id"], 18, "age-1"),
            (first, first["questions"][0]["id"], 30, "age-2"),
            (second, second["questions"][0]["id"], 30, "age-3"),
            (second, second["questions"][0]["id"], 42, "age-4"),
        ]
        for survey, question_id, value, token in response_rows:
            self.db.responses.insert_one(
                {
                    "surveyId": survey["_id"],
                    "surveyVersion": survey.get("version", 1),
                    "respondentId": None,
                    "anonymous": True,
                    "participantKey": None,
                    "submissionToken": token,
                    "submittedAt": now,
                    "answers": [
                        {
                            "questionId": question_id,
                            "type": "number",
                            "value": value,
                        }
                    ],
                    "visitedQuestionIds": [question_id],
                }
            )

        response = self.client.post(
            f"/question-bank/{family_id}/versions/new",
            data={
                "base_version_id": version_id,
                "save_mode": "new",
                "type": "text",
                "title": "年龄补充说明",
            },
            follow_redirects=True,
        )
        self.assertIn("新版本已保存", response.get_data(as_text=True))
        family = self.db.question_bank.documents[0]
        text_version_id = family["currentVersionId"]
        self.create_survey(self.client, "第三份文本年龄问卷")
        third = self.db.surveys.documents[2]
        self.client.post(
            f"/surveys/{third['_id']}/questions/from-bank",
            data={"bank_version_id": text_version_id},
            follow_redirects=True,
        )
        third_question_id = third["questions"][0]["id"]
        for index, value in enumerate(["30", "未知"], start=1):
            self.db.responses.insert_one(
                {
                    "surveyId": third["_id"],
                    "surveyVersion": third.get("version", 1),
                    "respondentId": None,
                    "anonymous": True,
                    "participantKey": None,
                    "submissionToken": f"age-text-{index}",
                    "submittedAt": now,
                    "answers": [
                        {
                            "questionId": third_question_id,
                            "type": "text",
                            "value": value,
                        }
                    ],
                    "visitedQuestionIds": [third_question_id],
                }
            )

        response = self.client.post(
            f"/question-bank/{family_id}/versions/new",
            data={
                "base_version_id": version_id,
                "save_mode": "new",
                "type": "single_choice",
                "title": "年龄段",
                "options": "青年\n中年",
            },
            follow_redirects=True,
        )
        self.assertIn("新版本已保存", response.get_data(as_text=True))
        family = self.db.question_bank.documents[0]
        choice_version_id = family["currentVersionId"]
        self.create_survey(self.client, "第四份年龄段问卷")
        fourth = self.db.surveys.documents[3]
        self.client.post(
            f"/surveys/{fourth['_id']}/questions/from-bank",
            data={"bank_version_id": choice_version_id},
            follow_redirects=True,
        )
        fourth_question = fourth["questions"][0]
        choice_young = fourth_question["options"][0]["id"]
        choice_middle = fourth_question["options"][1]["id"]
        for index, value in enumerate(
            [choice_young, choice_middle, choice_young],
            start=1,
        ):
            self.db.responses.insert_one(
                {
                    "surveyId": fourth["_id"],
                    "surveyVersion": fourth.get("version", 1),
                    "respondentId": None,
                    "anonymous": True,
                    "participantKey": None,
                    "submissionToken": f"age-choice-{index}",
                    "submittedAt": now,
                    "answers": [
                        {
                            "questionId": fourth_question["id"],
                            "type": "single_choice",
                            "value": value,
                        }
                    ],
                    "visitedQuestionIds": [fourth_question["id"]],
                }
            )

        page = self.client.get(
            f"/question-bank/insights/{family_id}"
        )
        text = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn(str(first["_id"]), text)
        self.assertIn(str(second["_id"]), text)
        self.assertIn("跨问卷", text)
        self.assertIn("分问卷答题分析", text)
        self.assertIn("青年", text)
        self.assertIn("平均值", text)

        api = self.client.get(
            f"/api/v1/question-bank/insights/{family_id}"
        )
        payload = api.get_json()
        self.assertEqual(api.status_code, 200)
        self.assertEqual(payload["surveyCount"], 4)
        self.assertEqual(payload["usageCount"], 4)
        self.assertEqual(payload["answeredCount"], 9)
        numeric = next(
            group["numeric"]
            for group in payload["typeGroups"]
            if group["type"] == "number"
        )
        self.assertEqual(numeric["average"], 30.0)
        self.assertEqual(numeric["median"], 30.0)
        text_group = next(
            group["text"]
            for group in payload["typeGroups"]
            if group["type"] == "text"
        )
        self.assertEqual(text_group["count"], 2)
        self.assertEqual(text_group["numeric"]["count"], 1)
        choice_group = next(
            group["choice"]
            for group in payload["typeGroups"]
            if group["type"] == "single_choice"
        )
        choice_counts = {
            option["label"]: option["count"]
            for option in choice_group["distribution"]
        }
        self.assertEqual(choice_counts, {"青年": 2, "中年": 1})
        self.assertEqual(len(payload["versionBreakdown"]), 3)

        lookup = self.client.get(
            "/question-bank/lookup",
            query_string={"question_id": version_id},
        )
        self.assertEqual(lookup.status_code, 302)
        self.assertIn(
            f"/question-bank/insights/{version_id}",
            lookup.headers["Location"],
        )

        local_question_id = first["questions"][0]["id"]
        local_page = self.client.get(
            f"/question-bank/insights/{local_question_id}"
        )
        self.assertEqual(local_page.status_code, 200)

        self.client.post("/logout", follow_redirects=True)
        self.register(self.client, "bob")
        self.login(self.client, "bob")
        forbidden = self.client.get(
            f"/question-bank/insights/{family_id}"
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_published_survey_questions_are_read_only(self):
        self.register(self.client, "alice")
        self.login(self.client, "alice")
        self.create_survey(self.client, "只读发布问卷")
        survey = self.db.surveys.documents[0]
        self.add_question(
            self.client,
            survey["_id"],
            type="text",
            title="发布后不可删除",
            required="1",
        )
        question_id = survey["questions"][0]["id"]
        self.client.post(
            f"/surveys/{survey['_id']}/publish",
            follow_redirects=True,
        )
        response = self.client.post(
            f"/surveys/{survey['_id']}/questions/{question_id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(survey["questions"]), 1)
        self.assertEqual(survey["status"], "published")
if __name__ == "__main__":
    unittest.main()
