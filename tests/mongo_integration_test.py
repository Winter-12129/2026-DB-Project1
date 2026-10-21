"""验证 MongoDB Validator、聚合统计和索引执行计划。

该脚本使用独立测试数据库，运行结束后删除测试库。
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import ObjectId
from bson.codec_options import CodecOptions
from bson.json_util import dumps
from pymongo import MongoClient
from pymongo.errors import WriteError

from common.db import ensure_indexes
from common.schema import apply_schema_validators


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://127.0.0.1:27017",
)
DB_NAME = os.environ.get(
    "MONGO_TEST_DB_NAME",
    "survey_system_mongo_features_test",
)


def plan_stages(plan):
    if not plan:
        return []
    stages = [plan.get("stage")] if plan.get("stage") else []
    if isinstance(plan.get("inputStage"), dict):
        stages.extend(plan_stages(plan["inputStage"]))
    if isinstance(plan.get("inputStages"), list):
        for child in plan["inputStages"]:
            stages.extend(plan_stages(child))
    return stages


def execution_summary(explain):
    stats = explain.get("executionStats", {})
    return {
        "winningStages": plan_stages(explain.get("queryPlanner", {}).get("winningPlan", {})),
        "nReturned": stats.get("nReturned"),
        "totalKeysExamined": stats.get("totalKeysExamined"),
        "totalDocsExamined": stats.get("totalDocsExamined"),
        "executionTimeMillis": stats.get("executionTimeMillis"),
    }


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client.get_database(
        DB_NAME,
        codec_options=CodecOptions(
            unicode_decode_error_handler="replace",
        ),
    )
    try:
        client.drop_database(DB_NAME)
        apply_schema_validators(db)
        ensure_indexes(db)

        now = datetime.now(timezone.utc)
        survey_id = ObjectId()
        question = {
            "id": "q_number",
            "order": 1,
            "type": "number",
            "title": "数字题",
            "required": True,
            "options": [],
            "config": {"min": 0, "max": 100, "integerOnly": False},
        }
        survey = {
            "_id": survey_id,
            "ownerId": ObjectId(),
            "title": "Validator 与 Explain 测试",
            "description": "用于验证结构约束和索引执行计划",
            "allowAnonymous": True,
            "allowMultipleResponses": True,
            "shareCode": "explain001",
            "status": "published",
            "version": 1,
            "schemaVersion": 1,
            "startQuestionId": question["id"],
            "questions": [question],
            "rules": [],
            "deadline": None,
            "publishedAt": now,
            "closedAt": None,
            "createdAt": now,
            "updatedAt": now,
        }
        db.surveys.insert_one(survey)

        # 数据库级 validator 应拒绝非法状态。
        invalid_survey = dict(survey)
        invalid_survey.pop("_id")
        invalid_survey["shareCode"] = "invalid001"
        invalid_survey["status"] = "not-a-status"
        try:
            db.surveys.insert_one(invalid_survey)
        except WriteError:
            print("[OK] MongoDB Validator 拒绝非法 status")
        else:
            raise AssertionError("Validator 没有拒绝非法 status")

        responses = []
        for index in range(200):
            responses.append(
                {
                    "surveyId": survey_id,
                    "surveyVersion": 1,
                    "respondentId": None,
                    "anonymous": True,
                    "participantKey": None,
                    "submissionToken": f"explain-token-{index}",
                    "submittedAt": now,
                    "answers": [
                        {
                            "questionId": question["id"],
                            "type": "number",
                            "value": index,
                        }
                    ],
                    "visitedQuestionIds": [question["id"]],
                }
            )
        db.responses.insert_many(responses)

        # 数据库级 validator 应拒绝缺少 submissionToken 的答卷。
        invalid_response = dict(responses[0])
        invalid_response.pop("_id")
        invalid_response.pop("submissionToken")
        invalid_response["submissionAt"] = now
        try:
            db.responses.insert_one(invalid_response)
        except WriteError:
            print("[OK] MongoDB Validator 拒绝缺少 submissionToken 的答卷")
        else:
            raise AssertionError("Validator 没有拒绝非法答卷")

        survey_plan = db.surveys.find(
            {"shareCode": survey["shareCode"]}
        ).explain()
        response_plan = (
            db.responses.find(
                {"surveyId": survey_id, "surveyVersion": 1}
            )
            .sort("submittedAt", -1)
            .explain()
        )

        pipeline = [
            {
                "$match": {
                    "surveyId": survey_id,
                    "surveyVersion": 1,
                }
            },
            {
                "$unwind": "$answers"
            },
            {
                "$match": {
                    "answers.questionId": question["id"]
                }
            },
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "average": {"$avg": "$answers.value"},
                    "min": {"$min": "$answers.value"},
                    "max": {"$max": "$answers.value"},
                }
            },
        ]
        aggregate_result = list(db.responses.aggregate(pipeline))

        print("[OK] 聚合统计结果：", dumps(aggregate_result))
        print(
            "[OK] shareCode 查询计划：",
            dumps(execution_summary(survey_plan)),
        )
        print(
            "[OK] surveyVersion 查询计划：",
            dumps(execution_summary(response_plan)),
        )
    finally:
        client.drop_database(DB_NAME)
        client.close()


if __name__ == "__main__":
    main()
