from decimal import Decimal, InvalidOperation

from common.errors import ConflictError, NotFoundError, ValidationError
from common.ids import generate_option_id, generate_question_id
from common.time_utils import utc_now
from question_bank import service as bank_service
from surveys import repository as survey_repository
from surveys import service as survey_service

TYPE_LABELS = {
    "single_choice": "单选",
    "multiple_choice": "多选",
    "text": "文本",
    "number": "数字",
}


def _ensure_draft(document):
    if document.get("status") != "draft":
        raise ConflictError("只有草稿问卷可以修改题目")


def _parse_options(text, minimum):
    labels = [
        line.strip()
        for line in (text or "").splitlines()
        if line.strip()
    ]
    if len(labels) < minimum:
        raise ValidationError(f"该题型至少需要 {minimum} 个选项")
    return [
        {"id": generate_option_id(), "label": label}
        for label in labels
    ]


def _optional_int(value, field_name, minimum=0):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise ValidationError(f"{field_name}必须是整数") from exc
    if number < minimum:
        raise ValidationError(f"{field_name}不能小于 {minimum}")
    return number


def _optional_decimal(value, field_name):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{field_name}必须是数字") from exc
    if not number.is_finite():
        raise ValidationError(f"{field_name}必须是有限数字")
    return int(number) if number == number.to_integral_value() else float(number)


def _build_config(question_type, form):
    if question_type == "multiple_choice":
        minimum = _optional_int(
            form.get("min_selections"),
            "最少选择数量",
        ) or 0
        maximum = _optional_int(
            form.get("max_selections"),
            "最多选择数量",
        )
        if maximum is not None and maximum < minimum:
            raise ValidationError("最多选择数量不能小于最少选择数量")
        return {
            "minSelections": minimum,
            "maxSelections": maximum,
        }

    if question_type == "text":
        minimum = _optional_int(form.get("min_length"), "最少字数") or 0
        maximum = _optional_int(form.get("max_length"), "最多字数")
        if maximum is not None and maximum < minimum:
            raise ValidationError("最多字数不能小于最少字数")
        return {
            "minLength": minimum,
            "maxLength": maximum,
        }

    if question_type == "number":
        minimum = _optional_decimal(form.get("min_number"), "最小值")
        maximum = _optional_decimal(form.get("max_number"), "最大值")
        if (
            minimum is not None
            and maximum is not None
            and maximum < minimum
        ):
            raise ValidationError("最大值不能小于最小值")
        return {
            "min": minimum,
            "max": maximum,
            "integerOnly": form.get("integer_only") == "1",
        }

    return {}


def add_question(survey_id, owner_id, form):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    _ensure_draft(document)

    question_type = (form.get("type") or "").strip()
    if question_type not in TYPE_LABELS:
        raise ValidationError("请选择有效的题型")

    title = (form.get("title") or "").strip()
    if not title:
        raise ValidationError("题干不能为空")
    if len(title) > 300:
        raise ValidationError("题干不能超过 300 个字符")

    options = []
    if question_type == "single_choice":
        options = _parse_options(form.get("options"), 2)
    elif question_type == "multiple_choice":
        options = _parse_options(form.get("options"), 1)

    question = {
        "id": generate_question_id(),
        "order": len(document.get("questions", [])) + 1,
        "type": question_type,
        "title": title,
        "required": form.get("required") == "1",
        "options": options,
        "config": _build_config(question_type, form),
    }

    questions = list(document.get("questions", []))
    questions.append(question)
    fields = {
        "questions": questions,
        "updatedAt": utc_now(),
    }
    if not document.get("startQuestionId"):
        fields["startQuestionId"] = questions[0]["id"]
    survey_repository.update_fields(document["_id"], fields)
    return question


def add_from_bank(survey_id, owner_id, version_id, required=False):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    _ensure_draft(document)
    family, version = bank_service.get_accessible_version(owner_id, version_id)

    existing = next(
        (
            item
            for item in document.get("questions", [])
            if item.get("sourceVersionId") == version.get("id")
        ),
        None,
    )
    if existing is not None:
        raise ConflictError("这道题库题目已经添加到当前问卷")

    question = {
        "id": generate_question_id(),
        "order": len(document.get("questions", [])) + 1,
        "type": version["type"],
        "title": version["title"],
        "required": bool(required),
        "options": list(version.get("options", [])),
        "config": dict(version.get("config", {})),
        "sourceBankId": str(family["_id"]),
        "sourceVariantId": version["id"],
        "sourceVersionId": version["id"],
    }
    questions = list(document.get("questions", []))
    questions.append(question)
    fields = {
        "questions": questions,
        "updatedAt": utc_now(),
    }
    if not document.get("startQuestionId"):
        fields["startQuestionId"] = questions[0]["id"]
    survey_repository.update_fields(document["_id"], fields)
    return question


def delete_question(survey_id, owner_id, question_id):
    document = survey_service.get_owned_survey_doc(survey_id, owner_id)
    _ensure_draft(document)

    questions = list(document.get("questions", []))
    question = next(
        (item for item in questions if item.get("id") == question_id),
        None,
    )
    if question is None:
        raise NotFoundError("题目不存在")

    for rule in document.get("rules", []):
        clauses = rule.get("when", {}).get("clauses", [])
        referenced = (
            rule.get("fromQuestionId") == question_id
            or rule.get("action", {}).get("targetQuestionId") == question_id
            or any(
                clause.get("questionId") == question_id
                for clause in clauses
            )
        )
        if referenced:
            raise ConflictError("请先删除引用该题目的跳转规则")

    questions = [
        item for item in questions if item.get("id") != question_id
    ]
    for index, item in enumerate(questions, start=1):
        item["order"] = index

    survey_repository.update_fields(
        document["_id"],
        {
            "questions": questions,
            "startQuestionId": questions[0]["id"] if questions else None,
            "updatedAt": utc_now(),
        },
    )


def _config_summary(question):
    question_type = question.get("type")
    config = question.get("config", {})
    if question_type == "multiple_choice":
        maximum = config.get("maxSelections")
        return (
            f"至少 {config.get('minSelections', 0)} 项，"
            f"最多 {maximum if maximum is not None else '不限'} 项"
        )
    if question_type == "text":
        maximum = config.get("maxLength")
        return (
            f"{config.get('minLength', 0)}-"
            f"{maximum if maximum is not None else '不限'} 字"
        )
    if question_type == "number":
        minimum = config.get("min")
        maximum = config.get("max")
        integer_text = "，仅整数" if config.get("integerOnly") else ""
        return f"{minimum if minimum is not None else '不限'} 到 {maximum if maximum is not None else '不限'}{integer_text}"
    return f"{len(question.get('options', []))} 个选项"


def question_views(document):
    questions = sorted(
        document.get("questions", []),
        key=lambda item: item.get("order", 0),
    )
    return [
        {
            "id": question["id"],
            "order": question.get("order", index + 1),
            "type": question["type"],
            "typeLabel": TYPE_LABELS.get(
                question["type"],
                question["type"],
            ),
            "title": question["title"],
            "required": bool(question.get("required")),
            "options": question.get("options", []),
            "config": question.get("config", {}),
            "configSummary": _config_summary(question),
        }
        for index, question in enumerate(questions)
    ]


def public_questions(document):
    return [
        {
            "id": question["id"],
            "order": question.get("order", index + 1),
            "type": question["type"],
            "title": question["title"],
            "required": bool(question.get("required")),
            "options": question.get("options", []),
            "config": question.get("config", {}),
        }
        for index, question in enumerate(
            sorted(
                document.get("questions", []),
                key=lambda item: item.get("order", 0),
            )
        )
    ]


def get_question(document, question_id):
    return next(
        (
            question
            for question in document.get("questions", [])
            if question.get("id") == question_id
        ),
        None,
    )


def validate_questions_for_publish(document):
    questions = document.get("questions", [])
    if not questions:
        raise ValidationError("发布前至少需要一道题")

    question_ids = set()
    for question in questions:
        question_id = question.get("id")
        if not question_id or question_id in question_ids:
            raise ValidationError("题目 ID 缺失或重复")
        question_ids.add(question_id)
        if question.get("type") not in TYPE_LABELS:
            raise ValidationError("存在未知题型")
        if not (question.get("title") or "").strip():
            raise ValidationError("存在空题干")
        if question.get("type") in {"single_choice", "multiple_choice"}:
            option_ids = set()
            for option in question.get("options", []):
                if not option.get("id") or not option.get("label"):
                    raise ValidationError("选项 ID 或名称不能为空")
                if option["id"] in option_ids:
                    raise ValidationError("选项 ID 重复")
                option_ids.add(option["id"])
    start_question_id = document.get("startQuestionId")
    if start_question_id and start_question_id not in question_ids:
        raise ValidationError("问卷起始题不存在")


def _missing(value):
    return value is None or value == "" or value == []


def validate_answer(question, raw_value):
    question_type = question["type"]
    required = bool(question.get("required"))
    config = question.get("config", {})

    if _missing(raw_value):
        if required:
            raise ValidationError(f"“{question['title']}”是必填题")
        if (
            question_type == "multiple_choice"
            and config.get("minSelections", 0) > 0
        ):
            raise ValidationError(
                f"“{question['title']}”至少选择 "
                f"{config.get('minSelections')} 项"
            )
        return None

    if question_type == "single_choice":
        value = str(raw_value)
        valid_ids = {option["id"] for option in question.get("options", [])}
        if value not in valid_ids:
            raise ValidationError(f"“{question['title']}”的选项无效")
        return value

    if question_type == "multiple_choice":
        if not isinstance(raw_value, list):
            raise ValidationError(f"“{question['title']}”的答案格式无效")
        values = list(dict.fromkeys(str(value) for value in raw_value))
        valid_ids = {option["id"] for option in question.get("options", [])}
        if any(value not in valid_ids for value in values):
            raise ValidationError(f"“{question['title']}”包含无效选项")
        minimum = config.get("minSelections", 0)
        maximum = config.get("maxSelections")
        if required and len(values) == 0:
            raise ValidationError(f"“{question['title']}”是必填题")
        if len(values) < minimum:
            raise ValidationError(
                f"“{question['title']}”至少选择 {minimum} 项"
            )
        if maximum is not None and len(values) > maximum:
            raise ValidationError(
                f"“{question['title']}”最多选择 {maximum} 项"
            )
        return values

    if question_type == "text":
        value = str(raw_value).strip()
        if required and not value:
            raise ValidationError(f"“{question['title']}”是必填题")
        if not value:
            return None
        minimum = config.get("minLength", 0)
        maximum = config.get("maxLength")
        if len(value) < minimum:
            raise ValidationError(
                f"“{question['title']}”至少需要 {minimum} 个字"
            )
        if maximum is not None and len(value) > maximum:
            raise ValidationError(
                f"“{question['title']}”不能超过 {maximum} 个字"
            )
        return value

    if question_type == "number":
        try:
            value = Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise ValidationError(f"“{question['title']}”必须是数字") from exc
        if not value.is_finite():
            raise ValidationError(f"“{question['title']}”必须是有限数字")
        if config.get("integerOnly") and value != value.to_integral_value():
            raise ValidationError(f"“{question['title']}”必须是整数")
        minimum = config.get("min")
        maximum = config.get("max")
        if minimum is not None and value < Decimal(str(minimum)):
            raise ValidationError(f"“{question['title']}”不能小于 {minimum}")
        if maximum is not None and value > Decimal(str(maximum)):
            raise ValidationError(f"“{question['title']}”不能大于 {maximum}")
        return int(value) if value == value.to_integral_value() else float(value)

    raise ValidationError("未知题型")
