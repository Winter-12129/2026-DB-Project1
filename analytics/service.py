from decimal import Decimal, InvalidOperation

from bson.decimal128 import Decimal128

from analytics import repository
from common.errors import NotFoundError
from questions.service import TYPE_LABELS
from surveys.service import get_owned_survey_doc, to_view


def _answer_values(responses, question_id):
    values = []
    for response in responses:
        for answer in response.get("answers", []):
            if answer.get("questionId") == question_id:
                values.append(answer.get("value"))
                break
    return values


def _visited_count(responses, question_id):
    return sum(
        1
        for response in responses
        if question_id in response.get("visitedQuestionIds", [])
    )


def _to_decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return number if number.is_finite() else None


def _numeric_summary(values):
    numbers = [
        number
        for value in values
        if (number := _to_decimal(value)) is not None
    ]
    if not numbers:
        return {
            "count": 0,
            "average": None,
            "min": None,
            "max": None,
        }
    average = sum(numbers) / Decimal(len(numbers))
    return {
        "count": len(numbers),
        "average": float(average),
        "min": float(min(numbers)),
        "max": float(max(numbers)),
    }


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    return float(value)


def _option_stats(question, values, multiple=False):
    options = question.get("options", [])
    counts = {option["id"]: 0 for option in options}
    for value in values:
        selected = value if multiple else [value]
        if not isinstance(selected, list):
            continue
        for option_id in set(selected):
            if option_id in counts:
                counts[option_id] += 1
    answered = len(values)
    return [
        {
            "id": option["id"],
            "label": option.get("label", option["id"]),
            "count": counts[option["id"]],
            "percentage": (
                round(counts[option["id"]] * 100 / answered, 1)
                if answered
                else 0.0
            ),
        }
        for option in options
    ]


def _question_stats(question, responses, survey_id=None, survey_version=None):
    question_id = question["id"]
    values = _answer_values(responses, question_id)
    stats = {
        "questionId": question_id,
        "order": question.get("order", 0),
        "type": question.get("type"),
        "typeLabel": TYPE_LABELS.get(
            question.get("type"),
            question.get("type"),
        ),
        "title": question.get("title", ""),
        "required": bool(question.get("required")),
        "sourceBankId": question.get("sourceBankId"),
        "sourceVersionId": (
            question.get("sourceVersionId")
            or question.get("sourceVariantId")
        ),
        "visitedCount": _visited_count(responses, question_id),
        "answeredCount": len(values),
        "options": [],
        "textAnswers": [],
        "numeric": None,
    }

    if repository.supports_aggregation() and survey_id is not None:
        aggregated = repository.aggregate_question_stats(
            survey_id,
            survey_version,
            question,
        )
        if aggregated is not None:
            stats["visitedCount"] = aggregated["visitedCount"]
            stats["answeredCount"] = aggregated["answeredCount"]
            if question.get("type") in {
                "single_choice",
                "multiple_choice",
            }:
                counts = aggregated["optionCounts"]
                stats["options"] = [
                    {
                        "id": option["id"],
                        "label": option.get("label", option["id"]),
                        "count": counts.get(option["id"], 0),
                        "percentage": (
                            round(counts.get(option["id"], 0) * 100 / stats["answeredCount"], 1)
                            if stats["answeredCount"]
                            else 0.0
                        ),
                    }
                    for option in question.get("options", [])
                ]
            elif question.get("type") == "text":
                stats["textAnswers"] = [
                    str(value) for value in aggregated["textValues"]
                ]
                stats["numeric"] = _numeric_summary(aggregated["textValues"])
            elif question.get("type") == "number":
                numeric = aggregated["numeric"] or {}
                stats["numeric"] = {
                    "count": numeric.get("count", 0),
                    "average": _to_float(numeric.get("average")),
                    "min": _to_float(numeric.get("min")),
                    "max": _to_float(numeric.get("max")),
                }
            return stats

    if question.get("type") == "single_choice":
        stats["options"] = _option_stats(question, values)
    elif question.get("type") == "multiple_choice":
        stats["options"] = _option_stats(question, values, multiple=True)
    elif question.get("type") == "text":
        stats["textAnswers"] = [
            str(value) for value in values
        ]
        stats["numeric"] = _numeric_summary(values)
    elif question.get("type") == "number":
        stats["numeric"] = _numeric_summary(values)
    return stats


def get_survey_stats(survey_id, owner_id, question_id=None):
    document = get_owned_survey_doc(survey_id, owner_id)
    all_questions = sorted(
        document.get("questions", []),
        key=lambda question: question.get("order", 0),
    )
    selected = None
    if question_id:
        selected = next(
            (
                question
                for question in all_questions
                if question.get("id") == question_id
            ),
            None,
        )
        if selected is None:
            raise NotFoundError("题目不存在")

    version = document.get("version", 1)
    use_aggregation = repository.supports_aggregation()
    responses = [] if use_aggregation else repository.list_responses(
        document["_id"],
        version,
    )
    questions_to_show = [selected] if selected else all_questions
    stats = [
        _question_stats(
            question,
            responses,
            survey_id=document["_id"],
            survey_version=version,
        )
        for question in questions_to_show
    ]
    return {
        "survey": to_view(document),
        "totalResponses": (
            repository.count_responses(document["_id"], version)
            if use_aggregation
            else len(responses)
        ),
        "surveyVersion": version,
        "allQuestions": [
            {
                "questionId": question["id"],
                "order": question.get("order", 0),
                "title": question.get("title", ""),
            }
            for question in all_questions
        ],
        "selectedQuestionId": question_id,
        "questions": stats,
    }
