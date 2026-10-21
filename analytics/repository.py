from common.db import get_db


def list_responses(survey_id, survey_version):
    """读取当前版本所有已提交答卷。

    统计数据按需从原始答卷计算，不维护容易失真的问卷内计数器。
    """

    return list(
        get_db()
        .responses.find(
            {
                "surveyId": survey_id,
                "surveyVersion": survey_version,
            }
        )
        .sort("submittedAt", 1)
    )


def count_responses(survey_id, survey_version):
    return get_db().responses.count_documents(
        {
            "surveyId": survey_id,
            "surveyVersion": survey_version,
        }
    )


def supports_aggregation():
    aggregate = getattr(get_db().responses, "aggregate", None)
    return callable(aggregate)


def aggregate_question_stats(survey_id, survey_version, question):
    """使用 MongoDB 聚合计算单题统计。

    测试替身没有 aggregate 方法时返回 None，由服务层走 Python 回退。
    """

    question_id = question["id"]
    question_type = question.get("type")
    answer_branch = [
        {"$unwind": "$answers"},
        {"$match": {"answers.questionId": question_id}},
    ]

    if question_type == "single_choice":
        answer_branch += [
            {
                "$group": {
                    "_id": "$answers.value",
                    "count": {"$sum": 1},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "key": "$_id",
                    "count": 1,
                }
            },
        ]
    elif question_type == "multiple_choice":
        answer_branch += [
            {"$unwind": "$answers.value"},
            {
                "$group": {
                    "_id": "$answers.value",
                    "count": {"$sum": 1},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "key": "$_id",
                    "count": 1,
                }
            },
        ]
    elif question_type == "text":
        answer_branch += [
            {
                "$group": {
                    "_id": None,
                    "values": {"$push": "$answers.value"},
                }
            }
        ]
    elif question_type == "number":
        answer_branch += [
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "average": {"$avg": "$answers.value"},
                    "min": {"$min": "$answers.value"},
                    "max": {"$max": "$answers.value"},
                }
            }
        ]
    else:
        return None

    pipeline = [
        {
            "$match": {
                "surveyId": survey_id,
                "surveyVersion": survey_version,
            }
        },
        {
            "$facet": {
                "visited": [
                    {"$match": {"visitedQuestionIds": question_id}},
                    {"$count": "count"},
                ],
                "answers": answer_branch,
            }
        },
    ]
    result = list(get_db().responses.aggregate(pipeline))
    if not result:
        return {
            "visitedCount": 0,
            "answeredCount": 0,
            "optionCounts": {},
            "textValues": [],
            "numeric": None,
        }

    facet = result[0]
    visited = facet.get("visited", [])
    visited_count = visited[0]["count"] if visited else 0
    answer_rows = facet.get("answers", [])

    if question_type in {"single_choice", "multiple_choice"}:
        option_counts = {
            row["key"]: row["count"]
            for row in answer_rows
            if row.get("key") is not None
        }
        return {
            "visitedCount": visited_count,
            "answeredCount": sum(option_counts.values()),
            "optionCounts": option_counts,
            "textValues": [],
            "numeric": None,
        }

    if question_type == "text":
        values = (
            answer_rows[0].get("values", [])
            if answer_rows
            else []
        )
        return {
            "visitedCount": visited_count,
            "answeredCount": len(values),
            "optionCounts": {},
            "textValues": values,
            "numeric": None,
        }

    numeric = answer_rows[0] if answer_rows else {}
    return {
        "visitedCount": visited_count,
        "answeredCount": numeric.get("count", 0),
        "optionCounts": {},
        "textValues": [],
        "numeric": numeric,
    }
