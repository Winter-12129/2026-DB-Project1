import math
from collections import Counter
from decimal import Decimal, InvalidOperation

from analytics import repository
from common.time_utils import format_local_datetime, utc_now
from question_bank import service as bank_service
from questions.service import TYPE_LABELS


def _to_decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _round(value, digits=2):
    return round(float(value), digits) if value is not None else None


def _percentile(values, ratio):
    if not values:
        return None
    index = max(0, min(len(values) - 1, math.ceil(len(values) * ratio) - 1))
    return values[index]


def _numeric_analysis(values):
    numbers = [
        number
        for value in values
        if (number := _to_decimal(value)) is not None
    ]
    if not numbers:
        return {
            "count": 0,
            "average": None,
            "median": None,
            "min": None,
            "max": None,
            "range": None,
            "standardDeviation": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "integerCount": 0,
            "decimalCount": 0,
            "histogram": [],
        }

    ordered = sorted(numbers)
    count = Decimal(len(numbers))
    average = sum(numbers) / count
    variance = sum((number - average) ** 2 for number in numbers) / count
    integer_count = sum(
        1 for number in numbers if number == number.to_integral_value()
    )
    minimum = ordered[0]
    maximum = ordered[-1]

    histogram = []
    if minimum == maximum:
        histogram = [
            {
                "label": f"{_round(minimum)}",
                "count": len(ordered),
                "percentage": 100.0,
            }
        ]
    else:
        bin_count = min(8, max(3, int(math.sqrt(len(ordered))) + 1))
        width = (maximum - minimum) / Decimal(bin_count)
        counts = [0 for _ in range(bin_count)]
        for number in ordered:
            index = int((number - minimum) / width)
            index = min(bin_count - 1, max(0, index))
            counts[index] += 1
        for index, bin_total in enumerate(counts):
            start = minimum + width * index
            end = maximum if index == bin_count - 1 else start + width
            brackets = "[" if index == 0 else "("
            histogram.append(
                {
                    "label": (
                        f"{brackets}{_round(start)}，{_round(end)}]"
                    ),
                    "count": bin_total,
                    "percentage": round(bin_total * 100 / len(ordered), 1),
                }
            )

    return {
        "count": len(numbers),
        "average": _round(average),
        "median": _round(_percentile(ordered, 0.5)),
        "min": _round(minimum),
        "max": _round(maximum),
        "range": _round(maximum - minimum),
        "standardDeviation": _round(variance.sqrt()),
        "p25": _round(_percentile(ordered, 0.25)),
        "p75": _round(_percentile(ordered, 0.75)),
        "p90": _round(_percentile(ordered, 0.90)),
        "integerCount": integer_count,
        "decimalCount": len(numbers) - integer_count,
        "histogram": histogram,
    }


def _text_analysis(values):
    texts = [str(value) for value in values]
    if not texts:
        return {
            "count": 0,
            "uniqueCount": 0,
            "averageLength": None,
            "minLength": None,
            "maxLength": None,
            "topValues": [],
            "answers": [],
            "numeric": _numeric_analysis([]),
        }
    lengths = [len(text) for text in texts]
    frequencies = Counter(texts)
    top_values = [
        {"value": value, "count": count}
        for value, count in frequencies.most_common(10)
    ]
    return {
        "count": len(texts),
        "uniqueCount": len(frequencies),
        "averageLength": round(sum(lengths) / len(lengths), 1),
        "minLength": min(lengths),
        "maxLength": max(lengths),
        "topValues": top_values,
        "answers": texts,
        "numeric": _numeric_analysis(texts),
    }


def _choice_distribution(question, values, multiple):
    counts = {}
    labels = {}
    order = []
    for option in question.get("options", []):
        option_id = option.get("id")
        label = option.get("label", option_id)
        key = bank_service.normalize_text(label) or str(option_id)
        if key not in counts:
            counts[key] = 0
            labels[key] = label
            order.append(key)

    for value in values:
        selected = value if multiple else [value]
        if not isinstance(selected, list):
            continue
        for option_id in set(str(item) for item in selected):
            key = next(
                (
                    bank_service.normalize_text(option.get("label", ""))
                    or str(option.get("id"))
                    for option in question.get("options", [])
                    if str(option.get("id")) == option_id
                ),
                option_id,
            )
            if key not in counts:
                counts[key] = 0
                labels[key] = option_id
                order.append(key)
            counts[key] += 1

    answered = len(values)
    return [
        {
            "label": labels[key],
            "count": counts[key],
            "percentage": (
                round(counts[key] * 100 / answered, 1) if answered else 0.0
            ),
        }
        for key in order
    ]


def _merge_choice_types(question_type, usages):
    counts = {}
    labels = {}
    order = []
    answered = 0
    total_selections = 0
    for usage in usages:
        answered += usage["answeredCount"]
        for option in usage["choice"]:
            key = bank_service.normalize_text(option["label"]) or option["label"]
            if key not in counts:
                counts[key] = 0
                labels[key] = option["label"]
                order.append(key)
            counts[key] += option["count"]
            total_selections += option["count"]

    distribution = [
        {
            "label": labels[key],
            "count": counts[key],
            "percentage": (
                round(counts[key] * 100 / answered, 1) if answered else 0.0
            ),
        }
        for key in order
    ]
    distribution.sort(key=lambda item: item["count"], reverse=True)
    return {
        "distribution": distribution,
        "totalSelections": total_selections,
        "averageSelections": (
            round(total_selections / answered, 2) if answered else None
        ),
        "isMultiple": question_type == "multiple_choice",
    }


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


def _usage_analysis(usage, responses):
    question = usage["question"]
    question_type = question.get("type")
    values = _answer_values(responses, question.get("id"))
    choice = []
    numeric = _numeric_analysis([])
    text = _text_analysis([])
    if question_type in {"single_choice", "multiple_choice"}:
        choice = _choice_distribution(
            question,
            values,
            multiple=question_type == "multiple_choice",
        )
    elif question_type == "number":
        numeric = _numeric_analysis(values)
    elif question_type == "text":
        text = _text_analysis(values)

    visited_count = _visited_count(responses, question.get("id"))
    answered_count = len(values)
    return {
        "questionType": question_type,
        "typeLabel": TYPE_LABELS.get(question_type, question_type),
        "questionTitle": question.get("title", ""),
        "choice": choice,
        "numeric": numeric,
        "text": text,
        "values": values,
        "submittedCount": len(responses),
        "visitedCount": visited_count,
        "answeredCount": answered_count,
        "visitRate": (
            round(visited_count * 100 / len(responses), 1) if responses else 0.0
        ),
        "answerRate": (
            round(answered_count * 100 / visited_count, 1)
            if visited_count
            else 0.0
        ),
    }


def get_cross_survey_stats(viewer_id, reference):
    family, selected_version, reference_type = (
        bank_service.resolve_question_reference(viewer_id, reference)
    )
    usages = bank_service.question_usages(
        viewer_id,
        family,
        selected_version=selected_version,
    )

    response_cache = {}
    response_keys = set()
    response_dates = []
    usage_views = []
    type_buckets = {}
    version_buckets = {}
    versions_by_id = {
        version["id"]: version
        for version in bank_service.family_versions(family)
    }

    for usage in usages:
        survey = usage["survey"]
        survey_id = survey["_id"]
        survey_version = survey.get("version", 1)
        cache_key = (survey_id, survey_version)
        responses = response_cache.get(cache_key)
        if responses is None:
            responses = repository.list_responses(survey_id, survey_version)
            response_cache[cache_key] = responses

        analysis = _usage_analysis(usage, responses)
        usage_view = {
            "surveyId": usage["surveyId"],
            "surveyTitle": usage["surveyTitle"],
            "surveyStatus": usage["surveyStatus"],
            "surveyStatusLabel": usage["surveyStatusLabel"],
            "localQuestionId": usage["localQuestionId"],
            "sourceVersionId": usage["sourceVersionId"],
            "sourceVersionNumber": usage["sourceVersionNumber"],
            "submittedCount": analysis["submittedCount"],
            "visitedCount": analysis["visitedCount"],
            "answeredCount": analysis["answeredCount"],
            "visitRate": analysis["visitRate"],
            "answerRate": analysis["answerRate"],
            "questionType": analysis["questionType"],
            "typeLabel": analysis["typeLabel"],
            "questionTitle": analysis["questionTitle"],
            "analysis": {
                "choice": analysis["choice"],
                "numeric": analysis["numeric"],
                "text": analysis["text"],
            },
        }
        usage_views.append(usage_view)

        type_bucket = type_buckets.setdefault(
            analysis["questionType"],
            {
                "type": analysis["questionType"],
                "typeLabel": analysis["typeLabel"],
                "usageCount": 0,
                "visitedCount": 0,
                "answeredCount": 0,
                "choice": [],
                "numericValues": [],
                "textValues": [],
            },
        )
        type_bucket["usageCount"] += 1
        type_bucket["visitedCount"] += analysis["visitedCount"]
        type_bucket["answeredCount"] += analysis["answeredCount"]
        type_bucket["choice"].append(
            {
                "answeredCount": analysis["answeredCount"],
                "choice": analysis["choice"],
            }
        )
        type_bucket["numericValues"].extend(analysis["values"])
        type_bucket["textValues"].extend(analysis["values"])

        version_id = usage["sourceVersionId"] or "unknown"
        version_bucket = version_buckets.setdefault(
            version_id,
            {
                "versionId": version_id,
                "versionNumber": usage["sourceVersionNumber"],
                "versionTitle": (
                    versions_by_id.get(version_id, {}).get("title")
                    or analysis["questionTitle"]
                ),
                "usageCount": 0,
                "surveyIds": set(),
                "answeredCount": 0,
                "visitedCount": 0,
            },
        )
        version_bucket["usageCount"] += 1
        version_bucket["surveyIds"].add(usage["surveyId"])
        version_bucket["answeredCount"] += analysis["answeredCount"]
        version_bucket["visitedCount"] += analysis["visitedCount"]

        for response in responses:
            response_keys.add((usage["surveyId"], str(response.get("_id"))))
            submitted_at = response.get("submittedAt")
            if submitted_at is not None:
                response_dates.append(submitted_at)

    type_groups = []
    for question_type, bucket in type_buckets.items():
        group = {
            "type": question_type,
            "typeLabel": bucket["typeLabel"],
            "usageCount": bucket["usageCount"],
            "visitedCount": bucket["visitedCount"],
            "answeredCount": bucket["answeredCount"],
        }
        if question_type in {"single_choice", "multiple_choice"}:
            group["choice"] = _merge_choice_types(
                question_type,
                bucket["choice"],
            )
        elif question_type == "number":
            group["numeric"] = _numeric_analysis(bucket["numericValues"])
        elif question_type == "text":
            group["text"] = _text_analysis(bucket["textValues"])
        type_groups.append(group)

    version_breakdown = []
    for bucket in version_buckets.values():
        version_breakdown.append(
            {
                "versionId": bucket["versionId"],
                "versionNumber": bucket["versionNumber"],
                "versionTitle": bucket["versionTitle"],
                "usageCount": bucket["usageCount"],
                "surveyCount": len(bucket["surveyIds"]),
                "answeredCount": bucket["answeredCount"],
                "visitedCount": bucket["visitedCount"],
            }
        )
    version_breakdown.sort(
        key=lambda item: item.get("versionNumber") or 0,
        reverse=True,
    )

    submitted_count = sum(
        item["submittedCount"] for item in usage_views
    )
    visited_count = sum(item["visitedCount"] for item in usage_views)
    answered_count = sum(item["answeredCount"] for item in usage_views)
    selected_version_view = None
    if selected_version is not None:
        selected_version_view = {
            "id": selected_version.get("id"),
            "number": selected_version.get("number"),
            "title": selected_version.get("title", ""),
            "type": selected_version.get("type"),
            "typeLabel": TYPE_LABELS.get(
                selected_version.get("type"),
                selected_version.get("type"),
            ),
        }

    return {
        "reference": reference,
        "referenceType": reference_type,
        "family": {
            "id": str(family["_id"]),
            "title": family.get("title", ""),
            "isOwner": family.get("ownerId") == viewer_id,
        },
        "selectedVersion": selected_version_view,
        "usageCount": len(usage_views),
        "surveyCount": len({item["surveyId"] for item in usage_views}),
        "submittedCount": submitted_count,
        "uniqueResponseCount": len(response_keys),
        "visitedCount": visited_count,
        "answeredCount": answered_count,
        "answerRate": (
            round(answered_count * 100 / visited_count, 1)
            if visited_count
            else 0.0
        ),
        "firstSubmittedAt": (
            format_local_datetime(min(response_dates)) if response_dates else ""
        ),
        "lastSubmittedAt": (
            format_local_datetime(max(response_dates)) if response_dates else ""
        ),
        "usages": usage_views,
        "typeGroups": type_groups,
        "versionBreakdown": version_breakdown,
        "generatedAt": format_local_datetime(utc_now()),
    }