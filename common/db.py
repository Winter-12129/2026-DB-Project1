from flask import current_app
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError
from common.schema import apply_schema_validators


def init_db(app, database=None):
    """初始化 MongoDB；测试时可以传入一个内存数据库替身。"""

    if database is not None:
        app.extensions["mongo_db"] = database
        return

    client = MongoClient(
        app.config["MONGO_URI"],
        serverSelectionTimeoutMS=3000,
        tz_aware=True,
    )
    db = client[app.config["MONGO_DB_NAME"]]
    app.extensions["mongo_client"] = client
    app.extensions["mongo_db"] = db

    if app.config.get("MONGO_ENSURE_INDEXES", True):
        try:
            db.command("ping")
            apply_schema_validators(db)
            ensure_indexes(db)
        except PyMongoError as exc:
            raise RuntimeError(
                "无法连接 MongoDB，请确认 MongoDB 已启动，并检查 MONGO_URI。"
            ) from exc


def get_db():
    return current_app.extensions["mongo_db"]


def ensure_indexes(db):
    """建立第一阶段真正会用到的索引。"""

    db.users.create_index("username", unique=True, name="uniq_username")
    db.surveys.create_index(
        [("ownerId", ASCENDING), ("createdAt", DESCENDING)],
        name="owner_created",
    )
    db.surveys.create_index(
        "shareCode",
        unique=True,
        sparse=True,
        name="uniq_share_code",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("submittedAt", DESCENDING)],
        name="survey_submitted",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("surveyVersion", ASCENDING), ("submittedAt", DESCENDING)],
        name="survey_version_submitted",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("submissionToken", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "submissionToken": {"$type": "string"},
        },
        name="uniq_submission_token",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("participantKey", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "participantKey": {"$type": "string"},
        },
        name="uniq_participant",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("answers.questionId", ASCENDING)],
        name="answer_question",
    )
    db.responses.create_index(
        [("surveyId", ASCENDING), ("visitedQuestionIds", ASCENDING)],
        name="visited_question",
    )
